// 네이버 스마트스토어 / 브랜드스토어 추출 (isolated world).
// background.js 가 page world 에서 미리 dump 한 JSON-LD + __PRELOADED_STATE__ 를
// page_dump 인자로 받아서 파싱 + DOM detail 이미지 합침.

(() => {
  if (window.__qooHelperHandlerInstalled) return;
  window.__qooHelperHandlerInstalled = true;

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.type !== "EXTRACT") return false;
    extract(msg.config || {}, msg.page_dump || null)
      .then((data) => sendResponse(data))
      .catch((err) => sendResponse({ error: err?.message || String(err) }));
    return true;
  });

  async function extract(config, pageDump) {
    const url = location.href;
    const title = document.title || "";

    if (pageDump?.is_login_redirect || url.includes("nidlogin")) {
      return { error: "naver login redirect", redirect_url: url };
    }
    if (/captcha/i.test(title) || /시스템점검|비정상/.test(title)) {
      return { error: "captcha or block", title };
    }

    const out = {
      product_name: "",
      brand: "",
      price_krw: 0,
      cover_image_url: "",
      cover_images: [],
      options: [],
      shipping: { kind: null, amount: null, threshold: null },
      detail_image_urls: [],
      category_path: "",
      description: "",
      sources: [],
      page_url: url,
      page_title: title,
      extracted_at: new Date().toISOString(),
      extraction_version: "0.2.0",
      _warnings: [],
      _debug: {
        json_ld_count: pageDump?.json_ld_count ?? null,
        preloaded_keys: pageDump?.preloaded_keys ?? [],
        preloaded_total_size: pageDump?.preloaded_total_size ?? null,
        preloaded_subsizes: pageDump?.preloaded_subsizes ?? null,
        preloaded_dump_error: pageDump?.preloaded_dump_error ?? null,
        polled_attempts: pageDump?.polled_attempts ?? null,
        polled_until_filled: pageDump?.polled_until_filled ?? null,
        // options/shipping 분석용 — sub-store 원본 일부
        product_keys: pageDump?.preloaded_state?.product
          ? Object.keys(pageDump.preloaded_state.product).slice(0, 30)
          : null,
        product_delivery_dump: pageDump?.preloaded_state?.productDelivery ?? null,
        simple_product_keys: pageDump?.preloaded_state?.simpleProductForDetailPage
          ? Object.keys(pageDump.preloaded_state.simpleProductForDetailPage).slice(0, 30)
          : null,
        product_options_sample: (() => {
          const p = pageDump?.preloaded_state?.product;
          if (!p) return null;
          const opts = p.optionCombinations || p.options || p.optionInfo || null;
          return opts;
        })(),
      },
    };

    // 1) JSON-LD (background 가 page world 에서 dump)
    if (pageDump?.json_ld) {
      Object.assign(out, parseJsonLd(pageDump.json_ld));
      out.sources.push("json-ld");
    }

    // 2) __PRELOADED_STATE__ (Naver SPA payload)
    if (pageDump?.preloaded_state) {
      const fromPs = parsePreloadedState(pageDump.preloaded_state);
      mergeFill(out, fromPs);
      out.sources.push("preloaded-state");
    }

    // 3) page_title fallback — "제품명 : 셀러명" 패턴 (5/5 검증)
    if (!out.brand && title) {
      const m = title.match(/.+\s*:\s*(.+)$/);
      if (m && m[1]) {
        out.brand = m[1].trim();
        out.sources.push("title-brand");
      }
    }

    // 4) DOM 상세 이미지 — "상세 정보 펼치기" 클릭 → 스크롤 → 큰 img 필터
    if (config.extract_detail_images && out.detail_image_urls.length === 0) {
      // (4-a) Naver smartstore "상세 정보 펼치기" / "상품 정보 더보기" 버튼 클릭
      // 상세 영역이 collapsed 상태면 이미지 lazy-load 가 안 됨.
      try {
        const expandClicked = await tryExpandDetailSection();
        if (expandClicked) {
          out.sources.push("detail-expanded");
          await QooHelper.sleep(600);
        }
      } catch (_) {}
      try {
        await QooHelper.scrollToBottom(800, 200);
        await QooHelper.sleep(700);
      } catch (_) {}
      const detailImgs = extractDetailImagesByHeuristic(config.max_detail_images || 20);
      if (detailImgs.length > 0) {
        out.detail_image_urls = detailImgs;
        out.sources.push("dom-detail");
      }
    }

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

  // ──── JSON-LD Product → 표준 ────
  function parseJsonLd(d) {
    const out = {
      product_name: d.name || "",
      description: (d.description || "").slice(0, 500),
      category_path: typeof d.category === "string" ? d.category : "",
      brand: (typeof d.brand === "object" ? d.brand?.name : d.brand) || "",
      cover_image_url: "",
      cover_images: [],
      price_krw: 0,
    };
    const img = d.image;
    if (typeof img === "string") {
      out.cover_image_url = img;
      out.cover_images = [img];
    } else if (Array.isArray(img) && img.length > 0) {
      out.cover_image_url = img[0];
      out.cover_images = img.filter((u) => typeof u === "string");
    } else if (img && typeof img === "object") {
      const u = img.url || img["@id"];
      if (u) {
        out.cover_image_url = u;
        out.cover_images = [u];
      }
    }
    const offers = d.offers || {};
    const price =
      offers.price ?? offers.lowPrice ?? offers.priceSpecification?.price;
    const num = parseFloat(price);
    if (!isNaN(num)) out.price_krw = Math.round(num);
    return out;
  }

  // ──── __PRELOADED_STATE__ → 표준 ────
  // 네이버 스마트스토어 SPA 의 redux/zustand 같은 store dump.
  // 키 구조 (사장님 콘솔 검증):
  //   groupProduct        — 옵션 그룹
  //   productDelivery     — 배송 정보
  //   productBenefit      — 적립/혜택
  //   channelProductVertical — 카테고리
  //   forYouProduct       — 추천
  // 정확한 sub-key 는 페이지마다 변동 — deepFind 로 보수적 탐색.
  function parsePreloadedState(ps) {
    const out = {
      product_name: "",
      brand: "",
      price_krw: 0,
      cover_image_url: "",
      cover_images: [],
      options: [],
      shipping: { kind: null, amount: null, threshold: null },
      detail_image_urls: [],
    };

    // Naver redux store 는 keyed-by-ID (예: ps.product = {"A": {진짜}})
    const unwrap = (v) => {
      if (!v || typeof v !== "object") return null;
      if (Array.isArray(v)) return v[0] || null;
      const vals = Object.values(v);
      if (vals.length === 0) return null;
      const first = vals[0];
      if (first && typeof first === "object") return first;
      return v;
    };

    // product 객체 후보 — 다양한 위치 탐색
    const productCandidates = [
      unwrap(ps.product),
      unwrap(ps.simpleProductForDetailPage),
      unwrap(ps.channelProductVertical && ps.channelProductVertical.product),
      unwrap(ps.forYouProduct && ps.forYouProduct.product),
      unwrap(ps.groupProduct && ps.groupProduct.product),
      ps.channelProduct,
    ].filter((p) => p && typeof p === "object");

    let product = null;
    for (const cand of productCandidates) {
      if (cand && (cand.name || cand.productName || cand.salePrice || cand.dispSalePrice)) {
        product = cand;
        break;
      }
    }

    if (product) {
      out.product_name = product.name || product.productName || "";
      out.price_krw =
        parseInt(
          product.salePrice ||
            product.price ||
            product.dispSalePrice ||
            product.discountedSalePrice ||
            0,
          10,
        ) || 0;
      out.brand =
        product.brandName ||
        product.manufacturerName ||
        product.brand ||
        "";
    }

    // brand fallback — channel.channelName (= 셀러 이름)
    if (!out.brand) {
      const channelName = QooHelper.deepFind(ps, ["channel", "channelName"]);
      if (typeof channelName === "string" && channelName) {
        out.brand = channelName;
      }
    }
    if (product) {

      // 이미지
      const images = product.productImages || product.images || [];
      if (Array.isArray(images)) {
        for (const img of images) {
          const u =
            (typeof img === "string" && img) ||
            img?.url ||
            img?.imageUrl ||
            img?.imageUrlOrigin ||
            "";
          if (u && u.startsWith("http")) {
            if (!out.cover_image_url) out.cover_image_url = u;
            out.cover_images.push(u);
          }
        }
      }
      if (!out.cover_image_url) {
        out.cover_image_url =
          product.representImageUrl || product.representativeImageUrl || "";
        if (out.cover_image_url) out.cover_images.push(out.cover_image_url);
      }

      // 옵션
      const opts =
        product.optionCombinations ||
        product.options ||
        product.optionInfo?.optionCombinations ||
        [];
      if (Array.isArray(opts)) {
        for (const o of opts.slice(0, 50)) {
          if (!o || typeof o !== "object") continue;
          let name = o.optionName1 || o.name || o.displayName || "";
          if (o.optionName2) name = name ? `${name} / ${o.optionName2}` : o.optionName2;
          if (o.optionName3) name = `${name} / ${o.optionName3}`;
          const price =
            parseInt(o.price || o.optionPrice || out.price_krw || 0, 10) || 0;
          const inStock =
            o.stockQuantity == null ? true : Number(o.stockQuantity) > 0;
          if (name) {
            out.options.push({ name, price_krw: price, in_stock: inStock });
          }
        }
      }

      // detail content images
      const detail =
        product.detailContents ||
        product.detailImageUrls ||
        [];
      if (Array.isArray(detail)) {
        for (const u of detail.slice(0, 30)) {
          if (typeof u === "string" && u.startsWith("http")) {
            out.detail_image_urls.push(u);
          } else if (u?.imageUrl && u.imageUrl.startsWith("http")) {
            out.detail_image_urls.push(u.imageUrl);
          }
        }
      }
    }

    // shipping — productDelivery 도 keyed-by-ID 패턴
    const pd = unwrap(ps.productDelivery) || ps.productDelivery;
    if (pd && typeof pd === "object") {
      const fee = pd.baseFee ?? pd.deliveryFee ?? pd.fee ?? null;
      const thr =
        pd.freeShippingBaseAmount ??
        pd.conditionalFreeAmount ??
        pd.freeBaseAmount ??
        null;
      if (fee === 0) {
        out.shipping = { kind: "free", amount: 0, threshold: null };
      } else if (typeof fee === "number" && fee > 0) {
        if (thr) {
          out.shipping = {
            kind: "conditional",
            amount: fee,
            threshold: parseInt(thr, 10),
          };
        } else {
          out.shipping = { kind: "paid", amount: fee, threshold: null };
        }
      }
    }
    // shipping 도 product.productDeliveryInfo 안에 있을 수 있음 (이미 첫 if 에서 잡힘)
    // — 추가 보강: product.shippingFee 또는 product.shippingInfo
    if (!out.shipping.kind && product) {
      const sf = product.shippingFee ?? product.deliveryFee;
      if (sf === 0) out.shipping = { kind: "free", amount: 0, threshold: null };
      else if (typeof sf === "number") out.shipping = { kind: "paid", amount: sf, threshold: null };
    }

    return out;
  }

  // 빈 필드만 채움 (앞 source 우선)
  function mergeFill(target, src) {
    if (!src) return;
    for (const [k, v] of Object.entries(src)) {
      if (v == null) continue;
      if (k === "shipping") {
        if (!target.shipping?.kind) target.shipping = v;
      } else if (k === "options") {
        if (!target.options || target.options.length === 0) target.options = v;
      } else if (k === "cover_images") {
        if (!target.cover_images || target.cover_images.length === 0) {
          target.cover_images = v;
        }
      } else if (k === "detail_image_urls") {
        if (!target.detail_image_urls || target.detail_image_urls.length === 0) {
          target.detail_image_urls = v;
        }
      } else if (target[k] === "" || target[k] === 0 || target[k] == null) {
        target[k] = v;
      }
    }
  }

  // ──── DOM 상세 이미지 — 셀렉터 의존 X, 크기/위치 기반 휴리스틱 ────
  // 페이지의 모든 <img> 순회 → naturalWidth/Height 큰 + 페이지 중간 위치 +
  // exclude 패턴 미포함 만 통과. 셀러별 다른 컨테이너 클래스 무관.
  function extractDetailImagesByHeuristic(maxCount) {
    const all = Array.from(document.querySelectorAll("img"));
    if (all.length === 0) return [];
    const pageH = document.body.scrollHeight || 1;
    const exclude = [
      "banner", "event", "coupon", "shipping", "delivery",
      "return", "exchange", "notice", "guide", "footer",
      "logo_icon", "btn_", "ico_", "bg_", "thumb_",
      "/sticker/", "/icon/",
    ];

    const cands = [];
    for (const img of all) {
      const w = img.naturalWidth || 0;
      const h = img.naturalHeight || 0;
      if (w < 600 || h < 400) continue;             // 큰 이미지만
      if (w / h > 5 || h / w > 5) continue;          // 너무 가로/세로 긴 배너
      const src = (img.src || "").toLowerCase();
      if (!src || src.startsWith("data:")) continue;
      if (exclude.some((p) => src.includes(p))) continue;
      const rect = img.getBoundingClientRect();
      const top = rect.top + window.scrollY;
      const ratio = top / pageH;
      // 상단 슬라이더(0~0.18) + 하단 푸터(0.95~) 제외
      if (ratio < 0.18 || ratio > 0.95) continue;
      cands.push({
        url: QooHelper.toOriginalUrl(img.src),
        width: w,
        height: h,
        position_ratio: ratio,
        aspect_ratio: w / h,
      });
    }

    // 페이지 위치 순으로 정렬, 중복 URL 제거
    cands.sort((a, b) => a.position_ratio - b.position_ratio);
    const seen = new Set();
    const result = [];
    for (const c of cands) {
      if (seen.has(c.url)) continue;
      seen.add(c.url);
      c.index = result.length;
      result.push(c);
      if (result.length >= maxCount) break;
    }
    return result;
  }

  // Naver smartstore "상세 정보 펼치기" 버튼 클릭 — collapsed 영역 expand.
  // 이거 없으면 detail 이미지가 lazy-load 안 됨.
  // 다양한 라벨 패턴 + 클래스 패턴 시도. 클릭 성공 시 true.
  async function tryExpandDetailSection() {
    // 1) 텍스트 기반 — 모든 button 순회하며 "펼치기"/"더보기" 매치
    const candidates = [];
    for (const btn of document.querySelectorAll("button, a[role='button']")) {
      const txt = (btn.innerText || btn.textContent || "").trim();
      if (!txt || txt.length > 30) continue;
      if (/(상세\s*정보\s*펼치기|상품\s*정보\s*더보기|상세\s*펼치기|상세\s*더보기|펼치기|더\s*보기)/.test(txt)) {
        candidates.push(btn);
      }
    }
    // 2) 클래스 기반 — Naver SPA 내부 버튼
    for (const sel of [
      "button[class*='_unfold_btn']",
      "button[class*='unfoldBtn']",
      "button[class*='ExpandButton']",
      "button[class*='_more_button']",
      "[class*='detail_unfold'] button",
    ]) {
      for (const el of document.querySelectorAll(sel)) {
        if (!candidates.includes(el)) candidates.push(el);
      }
    }
    let clickedAny = false;
    for (const btn of candidates.slice(0, 3)) {
      try {
        // 화면에 보이도록 scroll
        btn.scrollIntoView({ behavior: "instant", block: "center" });
        await QooHelper.sleep(150);
        btn.click();
        clickedAny = true;
        await QooHelper.sleep(300);
      } catch (_) {}
    }
    return clickedAny;
  }
})();
