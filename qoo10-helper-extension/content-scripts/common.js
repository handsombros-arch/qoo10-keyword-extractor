// 공통 유틸 — content script 간 공유.
// chrome.scripting.executeScript 으로 매번 새로 주입되므로 idempotent 하게 작성.

window.QooHelper = window.QooHelper || {};

QooHelper.sleep = (ms) => new Promise((r) => setTimeout(r, ms));

QooHelper.cleanText = (t) => (t || "").trim().replace(/\s+/g, " ");

// shop-phinf.pstatic.net?type=f260 등 리사이즈 파라미터 제거 → 원본 URL
QooHelper.toOriginalUrl = (src) => {
  if (!src || typeof src !== "string") return src;
  return src.replace(/\?type=[^&]*$/, "").replace(/\?.*$/, "");
};

// 페이지 끝까지 스크롤 (lazy-load 트리거)
QooHelper.scrollToBottom = async (stepPx = 600, delayMs = 250) => {
  const orig = window.scrollY;
  let cur = 0;
  const max = document.body.scrollHeight;
  while (cur < max) {
    cur += stepPx;
    window.scrollTo(0, cur);
    await QooHelper.sleep(delayMs);
  }
  window.scrollTo(0, orig);
};

// 모든 <script type="application/ld+json"> 파싱 → @type=Product 만 반환
QooHelper.extractJsonLd = () => {
  const scripts = document.querySelectorAll('script[type="application/ld+json"]');
  for (const s of scripts) {
    try {
      const data = JSON.parse(s.textContent);
      if (data && data["@type"] === "Product") return data;
      if (Array.isArray(data)) {
        for (const item of data) {
          if (item && item["@type"] === "Product") return item;
        }
      }
    } catch (_) {}
  }
  return null;
};

// __NEXT_DATA__ JSON 추출 (legacy fallback)
QooHelper.extractNextData = () => {
  const el = document.getElementById("__NEXT_DATA__");
  if (!el) return null;
  try {
    return JSON.parse(el.textContent);
  } catch (_) {
    return null;
  }
};

// nested object/array 에서 키 경로 깊이 우선 탐색 (최대 8단계)
QooHelper.deepFind = (obj, keyPath, depth = 0, maxDepth = 8) => {
  if (depth > maxDepth || !keyPath || keyPath.length === 0) return null;
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    if (keyPath[0] in obj) {
      if (keyPath.length === 1) return obj[keyPath[0]];
      const r = QooHelper.deepFind(obj[keyPath[0]], keyPath.slice(1), depth + 1, maxDepth);
      if (r != null) return r;
    }
    for (const v of Object.values(obj)) {
      const r = QooHelper.deepFind(v, keyPath, depth + 1, maxDepth);
      if (r != null) return r;
    }
  } else if (Array.isArray(obj)) {
    for (const v of obj) {
      const r = QooHelper.deepFind(v, keyPath, depth + 1, maxDepth);
      if (r != null) return r;
    }
  }
  return null;
};

// 상세 영역 이미지 필터링 (배너/아이콘 제거)
QooHelper.filterDetailImages = (imgs, maxCount = 20) => {
  const exclude = [
    "banner", "event", "coupon", "shipping", "delivery",
    "return", "exchange", "notice", "guide", "footer",
    "logo_icon", "btn_", "ico_", "bg_",
  ];
  const result = [];
  const pageH = document.body.scrollHeight || 1;
  for (const img of imgs) {
    const w = img.naturalWidth || 0;
    const h = img.naturalHeight || 0;
    if (w < 200 || h < 200) continue;
    if (w / h > 5) continue;     // 가로배너
    if (w <= 1 || h <= 1) continue;
    const src = (img.src || "").toLowerCase();
    if (exclude.some((p) => src.includes(p))) continue;
    const rect = img.getBoundingClientRect();
    result.push({
      url: QooHelper.toOriginalUrl(img.src),
      width: w,
      height: h,
      position_ratio: (rect.top + window.scrollY) / pageH,
      aspect_ratio: w / h,
      index: result.length,
    });
    if (result.length >= maxCount) break;
  }
  return result;
};
