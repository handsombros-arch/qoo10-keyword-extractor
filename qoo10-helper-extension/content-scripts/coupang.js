// 쿠팡 상세 페이지 추출 (isolated world).
// 사장님 메인 Chrome 에서 실행 — AKAMAI 차단 회피 (browser_manager Playwright 와 다름).
//
// Coupang 은 Naver 와 달리 __PRELOADED_STATE__ 없음 → DOM 셀렉터 + JSON-LD 만 사용.
// review-keyword 차단 / 정적자원 (front-web-next) 제외 휴리스틱은 백엔드 m_domestic_details.py
// 의 _fetch_coupang_via_browser_manager 에서 그대로 가져옴.

(() => {
  if (window.__qooHelperCoupangInstalled) return;
  window.__qooHelperCoupangInstalled = true;

  // review/평점 키워드 — 옵션과 모양이 비슷해서 자주 잘못 잡힘
  // Coupang 리뷰 분포 라벨: "모든 별점 / 최고 / 좋음 / 보통 / 별로 / 나쁨" (5단계)
  // ("좋아요" 아니라 "좋음" 임 — UI 표기 확인됨 5/3)
  const REVIEW_RE = /(별점|평점|리뷰|후기|평가|만족도|등급|stars?|rating|review|score|총점|모든\s*별점|좋음|좋아요|보통|별로|나쁨|최고|최악)/i;

  // 옵션 후보 셀렉터 — 너무 느슨한 [class*='Option'] li 는 제외
  const OPTION_SELECTORS = [
    "ul[class*='prod-option'] li",
    "select[class*='option'] option",
    "[class*='ProductOption'] li", "[class*='product-option'] li",
    "[class*='OptionSelect'] li", "[class*='option-select'] li",
    "[class*='SelectBox'] li",
    "[role='listbox'] [role='option']",
  ];

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.type !== "EXTRACT") return false;
    extract(msg.config || {})
      .then((data) => sendResponse(data))
      .catch((err) => sendResponse({ error: err?.message || String(err) }));
    return true;
  });

  async function extract(config) {
    const url = location.href;
    const title = document.title || "";

    // 차단 검사
    if (/Access\s*Denied/i.test(title)) {
      return { error: "coupang AKAMAI block (title=Access Denied)", title };
    }
    if (/captcha/i.test(title)) {
      return { error: "coupang captcha", title };
    }

    const out = {
      product_name: "",
      brand: "",
      price_krw: 0,
      cover_image_url: "",
      cover_images: [],
      options: [],
      shipping: { kind: null, amount: null, threshold: null },
      shipping_text: "",
      detail_image_urls: [],
      category_path: "",
      description: "",
      sources: [],
      page_url: url,
      page_title: title,
      extracted_at: new Date().toISOString(),
      extraction_version: "coupang-0.1.0",
      _warnings: [],
      _debug: {},
    };

    // 1) JSON-LD (있으면) — 쿠팡은 보통 없지만 일부 페이지에 있을 수 있음
    try {
      const ld = QooHelper.extractJsonLd();
      if (ld) {
        if (ld.name && !out.product_name) out.product_name = String(ld.name).slice(0, 200);
        if (ld.image && !out.cover_image_url) {
          out.cover_image_url = Array.isArray(ld.image) ? ld.image[0] : ld.image;
        }
        if (ld.brand && !out.brand) {
          out.brand = typeof ld.brand === "object" ? (ld.brand.name || "") : String(ld.brand);
        }
        if (ld.offers) {
          const price = ld.offers.price || ld.offers.lowPrice;
          if (price && !out.price_krw) out.price_krw = parseInt(String(price).replace(/[^\d]/g, ""), 10);
        }
        out.sources.push("json-ld");
      }
    } catch (_) {}

    // 2) 상품명 — page.title 또는 h1/h2 (제일 안정적)
    if (!out.product_name) {
      // page.title 형태: "상품명 - 쿠팡!" 또는 "상품명, 옵션 - 쿠팡!"
      const cleanedTitle = title.replace(/\s*[-|]\s*쿠팡!?\s*$/, "").trim();
      if (cleanedTitle && cleanedTitle.length >= 3) {
        out.product_name = cleanedTitle.slice(0, 200);
        out.sources.push("title");
      }
    }
    if (!out.product_name) {
      for (const sel of [".prod-buy-header__title", "h1.prod-buy-header__title", "h2.prod-name", "h1[class*='title']"]) {
        const el = document.querySelector(sel);
        if (el) {
          const t = QooHelper.cleanText(el.innerText || el.textContent || "");
          if (t && t.length >= 3) {
            out.product_name = t.slice(0, 200);
            out.sources.push("dom-h1");
            break;
          }
        }
      }
    }

    // 3) 가격 — 셀렉터 우선
    if (!out.price_krw) {
      const priceSelectors = [
        ".prod-price__sale .total-price strong",
        ".total-price strong",
        ".prod-price__price",
        "[class*='priceArea'] [class*='price']",
        "[class*='price'] strong",
        "[data-coupang-display-price]",
      ];
      for (const sel of priceSelectors) {
        const el = document.querySelector(sel);
        if (el) {
          const txt = QooHelper.cleanText(el.innerText || el.textContent || "");
          const v = parseKrwInt(txt);
          if (v) { out.price_krw = v; out.sources.push("dom-price"); break; }
        }
      }
    }
    // 가격 폴백 — HTML 정규식 (가장 빈출 숫자 = 메인 가격)
    if (!out.price_krw) {
      const html = document.documentElement.outerHTML.slice(0, 500_000); // 큰 페이지 잘라냄
      const matches = html.match(/\b\d{1,3}(?:,\d{3})+\b/g) || [];
      const counts = {};
      for (const m of matches) {
        const n = parseInt(m.replace(/,/g, ""), 10);
        if (n >= 1000 && n <= 10_000_000) counts[n] = (counts[n] || 0) + 1;
      }
      const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
      if (top) { out.price_krw = parseInt(top[0], 10); out.sources.push("html-regex-price"); }
    }

    // 4) 커버 이미지 — 큰 product 이미지 + 정적자원/아이콘 제외
    if (!out.cover_image_url) {
      const candidates = [];
      for (const img of document.querySelectorAll("img")) {
        const w = img.naturalWidth || img.width || 0;
        const h = img.naturalHeight || img.height || 0;
        const src = img.src || "";
        if (w >= 300 && h >= 300 && src.startsWith("http") && isProductImage(src)) {
          candidates.push({ w, h, src });
        }
      }
      candidates.sort((a, b) => (b.w * b.h) - (a.w * a.h));
      if (candidates.length > 0) {
        out.cover_image_url = candidates[0].src;
        out.cover_images = candidates.slice(0, 5).map((c) => c.src);
        out.sources.push("dom-cover");
      }
    }

    // 5) 옵션 — 드롭다운 클릭 트리거 후 추출
    try {
      for (const triggerSel of ["[class*='OptionSelect']", "[class*='option-select']", "button[class*='select']", "[role='combobox']"]) {
        const triggers = document.querySelectorAll(triggerSel);
        for (let i = 0; i < Math.min(triggers.length, 3); i++) {
          try {
            triggers[i].click();
            await QooHelper.sleep(300);
          } catch (_) {}
        }
      }
    } catch (_) {}

    // 보이지 않는 문자 (ZWSP/BOM/NBSP 등) 제거 — Coupang UI 가 가끔 삽입함
    const stripInvisible = (s) => (s || "")
      .replace(/[\u200b-\u200f\ufeff\u2028\u2029]/g, "") // ZWSP/RTL/FF marks
      .replace(/[\u00a0]/g, " ");                                  // NBSP -> space

    const seenOptNames = new Set();
    const priceMain = out.price_krw;
    let optsAdded = 0;
    const _debugOptsRaw = [];  // 매치 실패 시 디버깅용
    for (const sel of OPTION_SELECTORS) {
      const els = document.querySelectorAll(sel);
      if (els.length === 0 || els.length > 50) continue;
      let added = 0;
      for (const el of els) {
        try {
          let t = stripInvisible(QooHelper.cleanText(el.innerText || el.textContent || ""));
          if (!t || t.length > 80) continue;
          if (_debugOptsRaw.length < 10) _debugOptsRaw.push({ sel, t, len: t.length, codes: [...t].slice(0, 12).map((c) => c.charCodeAt(0)) });
          // review 패턴 차단
          if (REVIEW_RE.test(t)) continue;
          const price = parseKrwInt(t);
          let name = t.replace(/\d{1,3}(?:,\d{3})+\s*원?/g, "");
          name = name.replace(/수량\s*(증가|감소)|판매가|배송비|품절|sold\s*out/ig, "").trim().slice(0, 60);
          if (REVIEW_RE.test(name)) continue;
          const nameNoSpace = name.replace(/\s+/g, "");
          if (!nameNoSpace || nameNoSpace.length < 2 || /^\d+$/.test(nameNoSpace)) continue;
          if (["옵션", "선택", "필수", "default", "옵션 선택", "옵션선택"].includes(name.toLowerCase())) continue;
          const norm = name.toLowerCase();
          if (seenOptNames.has(norm)) continue;
          seenOptNames.add(norm);
          const optPrice = (price && price >= 1000) ? price : priceMain;
          if (optPrice) {
            out.options.push({ name, price_krw: optPrice, in_stock: true });
            added++;
            optsAdded++;
          }
        } catch (_) {}
      }
      if (added > 0) break;
    }
    out._debug.opts_raw = _debugOptsRaw;
    // 옵션 1개도 없으면 default 옵션 (가격만)
    if (out.options.length === 0 && priceMain) {
      out.options.push({ name: "default", price_krw: priceMain, in_stock: true });
    }
    if (optsAdded > 0) out.sources.push("dom-options");

    // 6) 배송비 텍스트
    let shipText = "";
    for (const sel of [".prod-shipping-fee", ".shipping-fee", "[class*='shipping']", "[class*='Shipping']", "[class*='Delivery'] [class*='fee']"]) {
      const els = document.querySelectorAll(sel);
      for (let i = 0; i < Math.min(els.length, 3); i++) {
        const t = QooHelper.cleanText(els[i].innerText || els[i].textContent || "");
        if (t && shipText.length < 200) shipText += " " + t;
      }
    }
    shipText = shipText.trim();
    out.shipping_text = shipText;
    // shipping 구조화 (Naver schema 와 정합)
    if (shipText) {
      if (/무료/i.test(shipText)) {
        out.shipping = { kind: "free", amount: 0, threshold: null };
      } else {
        const m = shipText.match(/(\d{1,3}(?:,\d{3})+)\s*원/);
        if (m) {
          const amt = parseInt(m[1].replace(/,/g, ""), 10);
          out.shipping = { kind: "paid", amount: amt, threshold: null };
        }
      }
      out.sources.push("dom-shipping");
    }

    // 7) detail content 이미지 — Coupang 은 비활성. 썸네일 (cover_images) 만 사용 (백엔드 다운로드 source).
    //   Coupang detail 페이지가 매우 길어 (50,000+ px) scrollToBottom 이 timeout (40s) 초과 유발.
    //   사장님 요청 (썸네일만 다운로드) 과도 정합. JP detail OCR 도 cover_images 로 충분.
    out.detail_image_urls = [];

    // 검증
    if (!out.product_name) out._warnings.push("missing_product_name");
    if (!out.price_krw) out._warnings.push("missing_price");
    if (!out.cover_image_url && (!out.cover_images || out.cover_images.length === 0)) {
      out._warnings.push("missing_cover_image");
    }
    if (out.sources.length === 0) out._warnings.push("no_extraction_source_matched");

    out.source = out.sources.join("+") || "none";
    return out;
  }

  // ──── 헬퍼 ────
  function parseKrwInt(text) {
    if (!text) return null;
    const m = String(text).match(/(\d{1,3}(?:,\d{3})+|\d{4,})/);
    if (!m) return null;
    const n = parseInt(m[1].replace(/,/g, ""), 10);
    return (n >= 100 && n <= 100_000_000) ? n : null;
  }

  function isProductImage(src) {
    if (!src || !src.startsWith("http")) return false;
    const s = src.toLowerCase();
    if (s.includes("_next/static/") || s.includes("/assets/icons")) return false;
    if (s.includes("front-web-next") || s.includes("front-web/")) return false;
    if (s.startsWith("data:")) return false;
    return true;
  }
})();
