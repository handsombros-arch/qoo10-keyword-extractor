// Qoo10 Helper — Service Worker
// 5초 단위 setInterval keepalive + chrome.alarms 1분 주기 폴링.
// 작업 중에는 setInterval 이 SW 깨워두고, 유휴 시엔 alarms 만 돌아 SW 종료 허용.

const BACKEND_URL = "http://localhost:8000";
const ALARM_NAME = "qoo10-helper-poll";
const POLL_PERIOD_MIN = 1;              // chrome.alarms minPeriod (production)
const KEEPALIVE_INTERVAL_MS = 25_000;   // SW 30s 자동 종료 회피
const PAGE_LOAD_TIMEOUT_MS = 30_000;
const EXTRACTION_TIMEOUT_MS = 40_000;     // page world polling 16s + content.js scroll/parse
const PAGE_DUMP_TIMEOUT_MS = 25_000;      // page world dump (polling 포함) 단독 한도
const DEFAULT_DELAY_MIN_MS = 3_000;
const DEFAULT_DELAY_MAX_MS = 5_000;

// in-memory state — SW 종료 시 chrome.storage.session 으로 보강
const STATE = {
  isRunning: false,
  currentJob: null,
  currentIndex: 0,
  currentTabId: null,
  startedAt: null,
  successCount: 0,
  errorCount: 0,
  recent: [],          // 최근 5건 [{url, status, ms}]
  lastError: null,
};

let keepaliveTimer = null;

// ──── alarm 등록 (idempotent) ────
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: POLL_PERIOD_MIN });
  console.log("[Qoo10 Helper] installed, poll alarm armed");
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: POLL_PERIOD_MIN });
});

// ──── alarm 폴링 ────
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== ALARM_NAME) return;
  if (STATE.isRunning) return;
  await pollNext();
});

// ──── popup → background 메시지 ────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "GET_STATUS") {
    sendResponse({
      isRunning: STATE.isRunning,
      job_id: STATE.currentJob?.job_id ?? null,
      index: STATE.currentIndex,
      total: STATE.currentJob?.urls?.length ?? 0,
      successCount: STATE.successCount,
      errorCount: STATE.errorCount,
      recent: STATE.recent.slice(-5),
      lastError: STATE.lastError,
      backendUrl: BACKEND_URL,
    });
    return false; // sync 응답
  }
  if (msg.type === "POLL_NOW") {
    pollNext().then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg.type === "PING_BACKEND") {
    fetch(`${BACKEND_URL}/api/auth/status`, { method: "GET" })
      .then((r) => sendResponse({ ok: r.ok, status: r.status }))
      .catch((e) => sendResponse({ ok: false, error: e.message }));
    return true;
  }
  return false;
});

// ──── 큐 폴링 ────
async function pollNext() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/ext/queue/next`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    if (res.status === 204) {
      updateBadge("idle");
      return;
    }
    if (!res.ok) {
      console.warn(`[Qoo10 Helper] queue/next ${res.status}`);
      return;
    }
    const job = await res.json();
    if (!job || !Array.isArray(job.urls) || job.urls.length === 0) return;

    STATE.isRunning = true;
    STATE.currentJob = job;
    STATE.currentIndex = 0;
    STATE.successCount = 0;
    STATE.errorCount = 0;
    STATE.recent = [];
    STATE.startedAt = Date.now();
    STATE.lastError = null;

    startKeepalive();
    updateBadge("working");
    await processNext();
  } catch (e) {
    // 백엔드 꺼져 있으면 조용히 무시
    console.log("[Qoo10 Helper] backend unreachable:", e.message);
    updateBadge("offline");
  }
}

// ──── URL 순차 처리 ────
async function processNext() {
  const job = STATE.currentJob;
  if (!job) return;
  if (STATE.currentIndex >= job.urls.length) {
    await finishJob();
    return;
  }

  const item = job.urls[STATE.currentIndex];
  updateBadge(`${STATE.currentIndex + 1}/${job.urls.length}`);

  const t0 = Date.now();
  let result = null;
  let err = null;
  let tabId = null;

  let prevActiveTabId = null;
  try {
    const cfg = job.config || {};
    const useActive = cfg.active_tab === true;

    if (useActive) {
      // 원래 active 탭 기억해뒀다가 끝나면 복원
      try {
        const [act] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (act) prevActiveTabId = act.id;
      } catch (_) {}
    }

    const tab = await chrome.tabs.create({
      url: item.url,
      active: useActive,
      pinned: false,
    });
    tabId = tab.id;
    STATE.currentTabId = tabId;

    await waitForTabComplete(tabId, PAGE_LOAD_TIMEOUT_MS);

    // settle 은 page world dump 안 polling 으로 통합 (최대 ~16초)
    // cfg.settle_ms 는 추가 sleep 으로만 사용 (호환)
    const extraSettleMs = cfg.settle_ms_extra ?? 0;
    if (extraSettleMs > 0) await sleep(extraSettleMs);

    // 1) page world 에서 JSON-LD + __PRELOADED_STATE__ 직접 dump (isolated world 우회)
    let pageDump = null;
    try {
      const [exec] = await chrome.scripting.executeScript({
        target: { tabId },
        world: "MAIN",
        func: pageWorldDump,
      });
      pageDump = exec?.result || null;
    } catch (e) {
      console.warn("[Qoo10 Helper] page world dump fail:", e.message);
    }

    // 2) content.js 주입 (isolated world) — DOM detail 이미지 + scroll
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content-scripts/common.js", "content-scripts/naver-smartstore.js"],
    });
    result = await sendMessageToTab(
      tabId,
      {
        type: "EXTRACT",
        config: {
          extract_detail_images: cfg.extract_detail_images ?? true,
          max_detail_images: cfg.max_detail_images ?? 20,
        },
        page_dump: pageDump,
      },
      EXTRACTION_TIMEOUT_MS,
    );
    if (!result || result.error) {
      err = result?.error || "no result";
      result = null;
    }
  } catch (e) {
    err = e.message || String(e);
  } finally {
    if (tabId != null) {
      try {
        await chrome.tabs.remove(tabId);
      } catch (_) {}
      STATE.currentTabId = null;
    }
    // active 모드였으면 원래 active 탭 복원 (사장님 작업 흐름 유지)
    if (prevActiveTabId != null) {
      try {
        await chrome.tabs.update(prevActiveTabId, { active: true });
      } catch (_) {}
    }
  }

  const elapsed = Date.now() - t0;
  if (result) {
    STATE.successCount++;
    STATE.recent.push({ url: item.url, status: "ok", ms: elapsed });
    await postResult({
      job_id: job.job_id,
      url: item.url,
      keyword_jp: item.keyword_jp,
      keyword_kr: item.keyword_kr,
      status: "success",
      data: result,
      elapsed_ms: elapsed,
    });
  } else {
    STATE.errorCount++;
    STATE.lastError = err;
    STATE.recent.push({ url: item.url, status: "err", ms: elapsed, error: err });
    await postResult({
      job_id: job.job_id,
      url: item.url,
      keyword_jp: item.keyword_jp,
      keyword_kr: item.keyword_kr,
      status: "error",
      error: err,
      elapsed_ms: elapsed,
    });
  }
  if (STATE.recent.length > 5) STATE.recent = STATE.recent.slice(-5);

  STATE.currentIndex++;

  const cfg = job.config || {};
  const minD = cfg.delay_min_ms ?? DEFAULT_DELAY_MIN_MS;
  const maxD = cfg.delay_max_ms ?? DEFAULT_DELAY_MAX_MS;
  const delay = minD + Math.random() * Math.max(0, maxD - minD);
  setTimeout(processNext, delay);
}

async function postResult(payload) {
  try {
    await fetchWithRetry(`${BACKEND_URL}/api/ext/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    console.warn("[Qoo10 Helper] postResult fail:", e.message);
  }
}

async function finishJob() {
  const job = STATE.currentJob;
  try {
    await fetchWithRetry(`${BACKEND_URL}/api/ext/queue/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: job?.job_id,
        total: job?.urls?.length ?? 0,
        success: STATE.successCount,
        errors: STATE.errorCount,
        elapsed_ms: Date.now() - STATE.startedAt,
      }),
    });
  } catch (e) {
    console.warn("[Qoo10 Helper] complete fail:", e.message);
  }
  STATE.isRunning = false;
  STATE.currentJob = null;
  stopKeepalive();
  updateBadge("idle");
}

// ──── util ────
function waitForTabComplete(tabId, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error(`tab load timeout ${timeoutMs}ms`));
    }, timeoutMs);
    function listener(updatedTabId, changeInfo) {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

function sendMessageToTab(tabId, message, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`extract timeout ${timeoutMs}ms`));
    }, timeoutMs);
    chrome.tabs.sendMessage(tabId, message, (response) => {
      clearTimeout(timer);
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(response);
      }
    });
  });
}

async function fetchWithRetry(url, options, maxRetries = 3) {
  let lastErr = null;
  for (let i = 0; i < maxRetries; i++) {
    try {
      const res = await fetch(url, options);
      if (res.ok || res.status === 204) return res;
      lastErr = new Error(`HTTP ${res.status}`);
    } catch (e) {
      lastErr = e;
    }
    await sleep(2000 * (i + 1));
  }
  throw lastErr;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function updateBadge(state) {
  if (state === "idle") {
    chrome.action.setBadgeText({ text: "" });
  } else if (state === "working") {
    chrome.action.setBadgeText({ text: "..." });
    chrome.action.setBadgeBackgroundColor({ color: "#4CAF50" });
  } else if (state === "offline") {
    chrome.action.setBadgeText({ text: "off" });
    chrome.action.setBadgeBackgroundColor({ color: "#9E9E9E" });
  } else {
    chrome.action.setBadgeText({ text: state });
    chrome.action.setBadgeBackgroundColor({ color: "#2196F3" });
  }
}

// ──── page world dump (isolated world 우회) ────
// chrome.scripting.executeScript({ world: 'MAIN', func: pageWorldDump }) 으로 호출.
// 페이지 SPA 의 window.__PRELOADED_STATE__ + JSON-LD 모두.
// 추가: PRELOADED_STATE.product / simpleProductForDetailPage 가 hydration 으로
//       채워질 때까지 polling (최대 ~16초). 채워지면 즉시 break.
async function pageWorldDump() {
  const out = {
    json_ld: null,
    json_ld_count: 0,
    preloaded_state: null,
    preloaded_keys: [],
    page_url: location.href,
    page_title: document.title,
    is_login_redirect: /nidlogin|nid\.naver\.com\/nidlogin/.test(location.href),
    polled_attempts: 0,
    polled_until_filled: false,
  };

  // Naver redux 는 entity store 를 keyed-by-ID 로 저장:
  //   ps.product = { "A": { 진짜 product } }
  //   ps.productDelivery = { "A": { ... } }
  // 첫 value 가 진짜 데이터.
  function unwrapKeyed(sub) {
    if (!sub || typeof sub !== "object") return null;
    if (Array.isArray(sub)) return sub[0] || null;
    const vals = Object.values(sub);
    if (vals.length === 0) return null;
    // 첫 값이 객체이고 의미있는 키 1개 이상이면 그게 진짜
    const first = vals[0];
    if (first && typeof first === "object") return first;
    return sub; // keyed 가 아닌 직접 객체
  }

  function isFilled() {
    const ps = window.__PRELOADED_STATE__;
    if (ps && typeof ps === "object") {
      const subs = [
        unwrapKeyed(ps.product),
        unwrapKeyed(ps.simpleProductForDetailPage),
        unwrapKeyed(ps.channelProductVertical && ps.channelProductVertical.product),
        unwrapKeyed(ps.forYouProduct && ps.forYouProduct.product),
      ];
      for (const p of subs) {
        if (!p || typeof p !== "object") continue;
        // 옵션/배송 정보까지 들어왔으면 hydration 진짜 끝남
        if (
          p.optionCombinations ||
          (Array.isArray(p.options) && p.options.length > 0) ||
          (p.optionInfo && Object.keys(p.optionInfo).length > 0) ||
          (p.productDeliveryInfo && p.productDeliveryInfo.baseFee != null)
        ) {
          return true;
        }
      }
    }
    return false;
  }

  function isMinimallyFilled() {
    // hydration 일부라도 — name/price 만 있어도 true. polling 마지막 단계 보조.
    const ps = window.__PRELOADED_STATE__;
    if (ps && typeof ps === "object") {
      const subs = [
        unwrapKeyed(ps.product),
        unwrapKeyed(ps.simpleProductForDetailPage),
      ];
      for (const p of subs) {
        if (
          p &&
          typeof p === "object" &&
          (p.name || p.productName || p.salePrice || p.dispSalePrice || p.representImageUrl)
        ) {
          return true;
        }
      }
    }
    for (const s of document.querySelectorAll(
      'script[type^="application/ld+json"]',
    )) {
      try {
        const d = JSON.parse(s.textContent);
        const items = Array.isArray(d) ? d : d && d["@graph"] ? d["@graph"] : [d];
        for (const it of items) {
          if (it && it["@type"] === "Product" && (it.name || it.offers)) return true;
        }
      } catch (_) {}
    }
    return false;
  }

  // 2단계 polling:
  //   1) isFilled() = options/shipping 까지 들어옴 → 즉시 break (이상적)
  //   2) isMinimallyFilled() = name/price 만 들어옴 → 추가 N초 더 기다리며 isFilled 재시도
  //   3) 둘 다 false → maxAttempts 까지 polling
  const maxAttempts = 25;
  const intervalMs = 800;
  let firstMinAttempt = -1;
  const extraAfterMin = 5; // minimally filled 후 5 attempts (4초) 더 기다림
  for (let i = 0; i < maxAttempts; i++) {
    out.polled_attempts = i + 1;
    if (isFilled()) {
      out.polled_until_filled = true;
      out.polled_full = true;
      await new Promise((r) => setTimeout(r, 400));
      break;
    }
    if (firstMinAttempt < 0 && isMinimallyFilled()) {
      firstMinAttempt = i;
    }
    if (firstMinAttempt >= 0 && i - firstMinAttempt >= extraAfterMin) {
      out.polled_until_filled = true;
      out.polled_full = false;
      break;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }

  // JSON-LD
  try {
    const els = document.querySelectorAll(
      'script[type^="application/ld+json"]',
    );
    out.json_ld_count = els.length;
    for (const s of els) {
      try {
        const d = JSON.parse(s.textContent);
        if (d && d["@type"] === "Product") {
          out.json_ld = d;
          break;
        }
        if (Array.isArray(d)) {
          for (const it of d) {
            if (it && it["@type"] === "Product") {
              out.json_ld = it;
              break;
            }
          }
          if (out.json_ld) break;
        }
        if (d && d["@graph"]) {
          for (const it of d["@graph"]) {
            if (it && it["@type"] === "Product") {
              out.json_ld = it;
              break;
            }
          }
          if (out.json_ld) break;
        }
      } catch (_) {}
    }
  } catch (_) {}

  // __PRELOADED_STATE__
  try {
    const ps = window.__PRELOADED_STATE__;
    if (ps && typeof ps === "object") {
      out.preloaded_keys = Object.keys(ps).slice(0, 40);
      const cleaned = JSON.parse(
        JSON.stringify(ps, (k, v) => (typeof v === "function" ? undefined : v)),
      );
      out.preloaded_state = cleaned;
      out.preloaded_total_size = JSON.stringify(cleaned).length;
      const subSizes = {};
      for (const k of Object.keys(cleaned).slice(0, 40)) {
        try {
          const sub = cleaned[k];
          if (sub && typeof sub === "object") {
            const j = JSON.stringify(sub);
            subSizes[k] = { len: j.length, keys: Object.keys(sub).slice(0, 8) };
          } else {
            subSizes[k] = { type: typeof sub, val: String(sub).slice(0, 30) };
          }
        } catch (_) {}
      }
      out.preloaded_subsizes = subSizes;
    }
  } catch (e) {
    out.preloaded_dump_error = String(e);
  }
  return out;
}

// ──── SW keepalive (작업 중에만) ────
function startKeepalive() {
  if (keepaliveTimer) return;
  keepaliveTimer = setInterval(() => {
    chrome.storage.session.set({ heartbeat: Date.now() });
  }, KEEPALIVE_INTERVAL_MS);
}
function stopKeepalive() {
  if (keepaliveTimer) {
    clearInterval(keepaliveTimer);
    keepaliveTimer = null;
  }
}
