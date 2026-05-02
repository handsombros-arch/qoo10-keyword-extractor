# Qoo10 Helper 크롬 확장 프로그램 설계서

> **목적**: CDP 9222 기반 네이버/쿠팡 스크래핑을 크롬 확장으로 대체하여 봇 탐지 회피 + 세션 관리 제거 + 안정성 확보
> **대상**: Claude Code 구현 컨텍스트
> **버전**: v1.0 (2026-05-02)
> **선행 문서**: `STATUS.md`, `AUTOMATION_FLOW.md`

---

## 0. 배경 — 왜 크롬 확장인가

### 0.1 현재 CDP 방식의 문제

```
백엔드 Python ──CDP 9222──▶ Chrome ──▶ 네이버/쿠팡
                  ↑
          여기서 문제 발생:
          • 네이버 봇 탐지 (WebDriver 플래그)
          • Chrome 147+ 보안 패치 → 메인 프로필 9222 차단
          • Naver 세션 30일 만료 → bat 파일로 수동 재로그인
          • CDP attach 불안정 → hang → R-6 keyword_only 원인
          • 별도 프로필 2개 관리 (qoo10-chrome-debug-profile, naver-browser-profile)
```

### 0.2 크롬 확장 방식

```
백엔드 Python ──HTTP──▶ 크롬 확장 (브라우저 내부) ──▶ 네이버/쿠팡
                              ↑
                    사장님 쿠키/세션 자동 사용
                    네이버 입장에선 "사용자가 보는 중"
                    봇 탐지 불가
```

### 0.3 해결되는 이슈 (STATUS.md 참조)

| 이슈 | 카테고리 | 상태 |
|------|---------|------|
| Chrome 147 메인 프로필 9222 차단 | B (외부 의존) | ✅ 해소 |
| Naver 세션 false negative | B | ✅ 해소 |
| Naver 30일 만료 | B | ✅ 해소 |
| CDP attach 의존 | B | ✅ 해소 |
| 옵션 dropdown 변종 | C (기술 난제) | ✅ 개선 (진짜 클릭) |

### 0.4 제거되는 파일/인프라

```
삭제 대상:
  automation/launch_chrome_debug.bat
  automation/open_naver_login_chrome.bat
  automation/setup_scheduler.ps1 → Qoo10ChromeDebug task 제거
  backend/app/services/naver_fetch_v2.py → 크롬 확장 클라이언트로 교체
  backend/app/services/naver_session_check.py → 불필요
  data/naver-browser-profile/ → 불필요
  %USERPROFILE%/qoo10-chrome-debug-profile/ → 불필요
```

---

## 1. 아키텍처

### 1.1 전체 흐름

```
┌─────────────────────────────────────────────────────────────┐
│  사장님 Chrome 브라우저                                       │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Qoo10 Helper 확장 프로그램                            │   │
│  │                                                        │   │
│  │  background.js (Service Worker)                        │   │
│  │    ├─ 5초 폴링: GET /api/ext/queue/next               │   │
│  │    ├─ 작업 수신 → 백그라운드 탭 생성                     │   │
│  │    ├─ content.js 결과 수신 → POST /api/ext/result      │   │
│  │    └─ 탭 닫기 → 딜레이 → 다음 작업                      │   │
│  │                                                        │   │
│  │  content.js (페이지 내부 실행)                           │   │
│  │    ├─ 네이버 스마트스토어 상세페이지                       │   │
│  │    │    ├─ "상세정보 더보기" 자동 클릭                     │   │
│  │    │    ├─ 스크롤 → lazy-load 이미지 대기                │   │
│  │    │    ├─ 상품명/가격/옵션/배송비 추출                   │   │
│  │    │    ├─ 커버 이미지 URL 수집 (원본 해상도)             │   │
│  │    │    ├─ 상세 이미지 URL 수집 + 크기/위치 필터링        │   │
│  │    │    └─ 결과 → background.js                         │   │
│  │    └─ 네이버 쇼핑 검색 결과 (선택, 향후 확장)             │   │
│  │                                                        │   │
│  │  popup.html (뱃지/상태)                                 │   │
│  │    └─ "처리 중: 3/40" / "대기 중" / "오류: 1건"          │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  사장님이 평소 쓰는 탭들 (방해 안 함)                          │
└─────────────────────────────────────────────────────────────┘
        ▲                          │
        │ HTTP (localhost:8000)     │
        │                          ▼
┌─────────────────────────────────────────────────────────────┐
│  백엔드 (FastAPI, localhost:8000)                             │
│                                                              │
│  새로 추가:                                                   │
│    POST /api/ext/queue          작업 등록 (URL 배열)          │
│    GET  /api/ext/queue/next     다음 작업 1건 반환             │
│    POST /api/ext/result         스크래핑 결과 수신             │
│    GET  /api/ext/status         큐 상태 (진행/완료/오류)       │
│                                                              │
│  기존 유지:                                                   │
│    OCR → LLM → 매칭 → SEO → 자동 빌드                       │
│    (입력 소스만 CDP → 크롬 확장 결과로 변경)                    │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 데이터 흐름 (STEP 5 기준)

```
[STEP 5] 한국 상품 검색 (네이버 쇼핑 API — 변경 없음)
    │
    │  검색 결과 URL 40건
    ▼
백엔드: POST /api/ext/queue
    │   body: {
    │     job_id: "2026-05-03_naver_detail",
    │     urls: [
    │       { url: "https://smartstore.naver.com/xxx/products/123", keyword_jp: "美容液", keyword_kr: "미용액" },
    │       { url: "https://smartstore.naver.com/yyy/products/456", keyword_jp: "化粧水", keyword_kr: "화장수" },
    │       ...
    │     ],
    │     config: {
    │       delay_ms: [3000, 5000],        // 랜덤 딜레이 범위
    │       extract_options: true,          // 옵션 순회 여부
    │       extract_detail_images: true,    // 상세 이미지 수집 여부
    │       max_detail_images: 20           // 상세 이미지 최대 수
    │     }
    │   }
    ▼
크롬 확장: 5초 폴링 → 작업 수신 → 순차 처리
    │
    │  URL 1건당:
    │  ① 백그라운드 탭 열기 (active: false)
    │  ② content.js 자동 주입 → 데이터 추출
    │  ③ POST /api/ext/result → 탭 닫기
    │  ④ 3~5초 대기 → 다음 URL
    ▼
백엔드: 결과 수신 → domestic_products INSERT/UPDATE
    │
    │  (이후 기존 파이프라인 동일)
    ▼
[STEP 5.5] OCR + set_count
[STEP 5.95] 매칭
[STEP 6.0] SEO 콘텐츠
```

---

## 2. 크롬 확장 파일 구조

```
qoo10-helper-extension/
├── manifest.json              # 확장 설정 (V3)
├── background.js              # Service Worker — 큐 폴링 + 탭 관리
├── content-scripts/
│   ├── naver-smartstore.js    # 스마트스토어 상세페이지 추출
│   ├── naver-brand.js         # 브랜드스토어 상세페이지 추출 (셀렉터 차이)
│   └── common.js              # 공통 유틸 (스크롤, 딜레이, 이미지 필터)
├── popup/
│   ├── popup.html             # 상태 표시 팝업
│   ├── popup.js
│   └── popup.css
├── icons/
│   ├── icon-16.png
│   ├── icon-48.png
│   └── icon-128.png
└── README.md                  # 설치 방법
```

---

## 3. manifest.json

```json
{
  "manifest_version": 3,
  "name": "Qoo10 Helper",
  "version": "1.0.0",
  "description": "Qoo10 자동화 도우미 — 네이버 상세 수집",

  "permissions": [
    "tabs",
    "activeTab",
    "scripting",
    "storage"
  ],

  "host_permissions": [
    "https://smartstore.naver.com/*",
    "https://brand.naver.com/*",
    "https://shopping.naver.com/*",
    "https://shop-phinf.pstatic.net/*",
    "http://localhost:8000/*"
  ],

  "background": {
    "service_worker": "background.js",
    "type": "module"
  },

  "content_scripts": [
    {
      "matches": [
        "https://smartstore.naver.com/*/products/*",
        "https://brand.naver.com/*/products/*"
      ],
      "js": [
        "content-scripts/common.js",
        "content-scripts/naver-smartstore.js"
      ],
      "run_at": "document_idle"
    }
  ],

  "action": {
    "default_popup": "popup/popup.html",
    "default_icon": {
      "16": "icons/icon-16.png",
      "48": "icons/icon-48.png",
      "128": "icons/icon-128.png"
    }
  },

  "icons": {
    "16": "icons/icon-16.png",
    "48": "icons/icon-48.png",
    "128": "icons/icon-128.png"
  }
}
```

**주의사항**:
- Manifest V3 필수 (V2는 2025년 이후 Chrome에서 비활성화)
- Service Worker는 비활성 시 자동 종료됨 → `chrome.alarms` API로 keepalive 필요
- `host_permissions`에 localhost 포함 → 백엔드 통신 허용

---

## 4. background.js — 핵심 로직

### 4.1 상태 관리

```javascript
// background.js

const STATE = {
  isRunning: false,
  currentJob: null,        // { job_id, urls[], config }
  currentIndex: 0,
  currentTabId: null,
  results: [],
  errors: [],
  startedAt: null
};

const BACKEND_URL = 'http://localhost:8000';
const POLL_INTERVAL_MS = 5000;           // 5초 폴링
const DEFAULT_DELAY = [3000, 5000];      // 페이지 간 딜레이 (ms)
const PAGE_LOAD_TIMEOUT_MS = 30000;      // 페이지 로드 타임아웃
const EXTRACTION_TIMEOUT_MS = 20000;     // 데이터 추출 타임아웃
```

### 4.2 폴링 루프

```javascript
// 5초마다 백엔드에 "할 일 있어?" 확인
chrome.alarms.create('poll-queue', { periodInMinutes: 0.083 }); // ≈5초

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== 'poll-queue') return;
  if (STATE.isRunning) return;  // 이미 작업 중이면 스킵

  try {
    const res = await fetch(`${BACKEND_URL}/api/ext/queue/next`);
    if (res.status === 204) return;  // 대기 작업 없음

    const job = await res.json();
    STATE.isRunning = true;
    STATE.currentJob = job;
    STATE.currentIndex = 0;
    STATE.results = [];
    STATE.errors = [];
    STATE.startedAt = Date.now();

    updateBadge('working');
    processNextUrl();
  } catch (e) {
    // 백엔드 꺼져 있으면 조용히 무시
    console.log('[Qoo10 Helper] 백엔드 연결 실패, 재시도 대기');
  }
});
```

### 4.3 URL 순차 처리

```javascript
async function processNextUrl() {
  const { urls, config } = STATE.currentJob;

  if (STATE.currentIndex >= urls.length) {
    await finishJob();
    return;
  }

  const item = urls[STATE.currentIndex];
  updateBadge(`${STATE.currentIndex + 1}/${urls.length}`);

  try {
    // 1. 백그라운드 탭 생성
    const tab = await chrome.tabs.create({
      url: item.url,
      active: false,        // 사장님 화면 방해 안 함
      pinned: false
    });
    STATE.currentTabId = tab.id;

    // 2. 페이지 로드 대기 (타임아웃 포함)
    await waitForTabLoad(tab.id, PAGE_LOAD_TIMEOUT_MS);

    // 3. content.js가 자동 실행되어 메시지를 보내올 때까지 대기
    //    (content_scripts에 등록된 도메인이면 자동 주입)
    //    등록 안 된 페이지면 수동 주입:
    //    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: [...] });

    // 4. content.js에 추출 시작 명령
    const result = await sendMessageToTab(tab.id, {
      type: 'EXTRACT',
      config: {
        extract_options: config.extract_options ?? true,
        extract_detail_images: config.extract_detail_images ?? true,
        max_detail_images: config.max_detail_images ?? 20
      }
    }, EXTRACTION_TIMEOUT_MS);

    // 5. 결과 백엔드 전송
    await fetch(`${BACKEND_URL}/api/ext/result`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: STATE.currentJob.job_id,
        url: item.url,
        keyword_jp: item.keyword_jp,
        keyword_kr: item.keyword_kr,
        status: 'success',
        data: result
      })
    });

    STATE.results.push({ url: item.url, status: 'success' });

  } catch (error) {
    // 개별 URL 실패 → 기록하고 계속 진행
    STATE.errors.push({ url: item.url, error: error.message });

    await fetch(`${BACKEND_URL}/api/ext/result`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: STATE.currentJob.job_id,
        url: item.url,
        status: 'error',
        error: error.message
      })
    });

  } finally {
    // 6. 탭 닫기
    if (STATE.currentTabId) {
      try { await chrome.tabs.remove(STATE.currentTabId); } catch {}
      STATE.currentTabId = null;
    }

    // 7. 랜덤 딜레이 후 다음 URL
    STATE.currentIndex++;
    const [minDelay, maxDelay] = STATE.currentJob.config.delay_ms || DEFAULT_DELAY;
    const delay = minDelay + Math.random() * (maxDelay - minDelay);
    setTimeout(processNextUrl, delay);
  }
}
```

### 4.4 작업 완료

```javascript
async function finishJob() {
  await fetch(`${BACKEND_URL}/api/ext/queue/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      job_id: STATE.currentJob.job_id,
      total: STATE.currentJob.urls.length,
      success: STATE.results.length,
      errors: STATE.errors.length,
      elapsed_ms: Date.now() - STATE.startedAt
    })
  });

  STATE.isRunning = false;
  STATE.currentJob = null;
  updateBadge('idle');
}
```

### 4.5 유틸

```javascript
function waitForTabLoad(tabId, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error(`Tab load timeout: ${timeoutMs}ms`));
    }, timeoutMs);

    function listener(updatedTabId, changeInfo) {
      if (updatedTabId === tabId && changeInfo.status === 'complete') {
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
      reject(new Error(`Extraction timeout: ${timeoutMs}ms`));
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

function updateBadge(state) {
  if (state === 'idle') {
    chrome.action.setBadgeText({ text: '' });
  } else if (state === 'working') {
    chrome.action.setBadgeText({ text: '...' });
    chrome.action.setBadgeBackgroundColor({ color: '#4CAF50' });
  } else {
    // "3/40" 같은 진행 텍스트
    chrome.action.setBadgeText({ text: state });
    chrome.action.setBadgeBackgroundColor({ color: '#2196F3' });
  }
}
```

### 4.6 Service Worker keepalive

Manifest V3 Service Worker는 30초 비활성 시 자동 종료됨. 작업 중에는 keepalive 필요.

```javascript
// 작업 중일 때 25초마다 ping (Service Worker 종료 방지)
let keepaliveInterval = null;

function startKeepalive() {
  if (keepaliveInterval) return;
  keepaliveInterval = setInterval(() => {
    if (STATE.isRunning) {
      chrome.runtime.getPlatformInfo(() => {}); // no-op으로 SW 유지
    }
  }, 25000);
}

function stopKeepalive() {
  if (keepaliveInterval) {
    clearInterval(keepaliveInterval);
    keepaliveInterval = null;
  }
}
```

---

## 5. content-scripts/common.js — 공통 유틸

```javascript
// ──── 딜레이 ────
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ──── 스크롤 → lazy-load 이미지 로딩 ────
async function scrollToBottom(stepPx = 500, delayMs = 300) {
  const maxScroll = document.body.scrollHeight;
  let current = 0;
  while (current < maxScroll) {
    current += stepPx;
    window.scrollTo(0, current);
    await sleep(delayMs);
  }
  // 마지막에 맨 위로 복귀
  window.scrollTo(0, 0);
}

// ──── 이미지 필터링 ────
function filterDetailImages(images, maxCount = 20) {
  return images
    .filter(img => {
      // 크기 필터: 너무 작은 이미지 제거 (아이콘, 배지 등)
      if (img.naturalWidth < 200 || img.naturalHeight < 200) return false;
      // 가로 배너 제거 (비율 5:1 이상)
      if (img.naturalWidth / img.naturalHeight > 5) return false;
      // 1x1 트래킹 픽셀 제거
      if (img.naturalWidth <= 1 || img.naturalHeight <= 1) return false;
      return true;
    })
    .filter(img => {
      // URL 패턴 필터
      const src = img.src.toLowerCase();
      const excludePatterns = [
        'banner', 'event', 'coupon', 'shipping', 'delivery',
        'return', 'exchange', 'notice', 'guide', 'footer',
        'logo_icon', 'btn_', 'ico_', 'bg_'
      ];
      return !excludePatterns.some(p => src.includes(p));
    })
    .slice(0, maxCount)
    .map((img, index) => {
      const rect = img.getBoundingClientRect();
      const pageHeight = document.body.scrollHeight;
      return {
        url: getOriginalImageUrl(img.src),
        width: img.naturalWidth,
        height: img.naturalHeight,
        position_ratio: rect.top / pageHeight,    // 페이지 내 위치 (0~1)
        index: index,
        aspect_ratio: img.naturalWidth / img.naturalHeight
      };
    });
}

// ──── 네이버 이미지 CDN URL → 원본 해상도 변환 ────
function getOriginalImageUrl(src) {
  // shop-phinf.pstatic.net 이미지: ?type=f260 등 리사이즈 파라미터 제거
  // → 원본 해상도 이미지 URL 반환
  return src
    .replace(/\?type=.*$/, '')        // ?type=f260, ?type=w860 등 제거
    .replace(/\?.*$/, '');            // 기타 쿼리스트링 제거
}

// ──── 텍스트 정리 ────
function cleanText(text) {
  return (text || '').trim().replace(/\s+/g, ' ');
}
```

---

## 6. content-scripts/naver-smartstore.js — 핵심 추출 로직

```javascript
// ──── 메시지 수신 (background.js → content.js) ────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type !== 'EXTRACT') return false;

  // 비동기 추출 후 응답
  extractProductData(msg.config)
    .then(data => sendResponse(data))
    .catch(err => sendResponse({ error: err.message }));

  return true;  // 비동기 응답 사용
});


// ──── 메인 추출 함수 ────
async function extractProductData(config) {
  const result = {
    // 기본 정보
    product_name: null,
    brand: null,
    price: null,
    original_price: null,
    discount_rate: null,
    category: null,

    // 옵션
    options: [],

    // 배송
    shipping: {
      kind: null,           // free / conditional / paid
      amount: null,
      threshold: null
    },

    // 이미지
    cover_images: [],        // 상단 썸네일 (원본 URL)
    detail_images: [],       // 상세 이미지 (필터링 + 메타데이터)

    // 메타
    extracted_at: new Date().toISOString(),
    page_url: window.location.href,
    extraction_version: '1.0'
  };

  // ──── 1. 기본 정보 ────
  result.product_name = extractProductName();
  result.brand = extractBrand();
  result.price = extractPrice();
  result.original_price = extractOriginalPrice();
  result.discount_rate = extractDiscountRate();
  result.category = extractCategory();
  result.shipping = extractShipping();

  // ──── 2. 커버 이미지 (상단 슬라이더) ────
  result.cover_images = extractCoverImages();

  // ──── 3. 옵션 추출 ────
  if (config.extract_options) {
    result.options = await extractOptions();
  }

  // ──── 4. 상세 이미지 ("더보기" 클릭 → 스크롤 → 수집) ────
  if (config.extract_detail_images) {
    await expandDetailSection();
    await scrollToBottom(500, 300);
    await sleep(1000);  // lazy-load 마지막 이미지 대기
    result.detail_images = extractDetailImages(config.max_detail_images);
  }

  return result;
}


// ──── 개별 추출 함수 ────

function extractProductName() {
  // 스마트스토어 상품명 셀렉터 (우선순위)
  const selectors = [
    '._3oDjSvLFlG',                           // 스마트스토어 v2
    '.product-title h3',                        // 구버전
    'h3[class*="productName"]',                // 클래스 패턴
    'meta[property="og:title"]'                // 폴백 (meta)
  ];

  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      return sel.startsWith('meta')
        ? el.getAttribute('content')
        : cleanText(el.textContent);
    }
  }
  return null;
}

function extractBrand() {
  const selectors = [
    '._1dByMwVYeE',                           // 브랜드 링크
    '.brand_area a',
    'a[class*="brand"]'
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return cleanText(el.textContent);
  }
  return null;
}

function extractPrice() {
  const selectors = [
    '._2pgHN-ntx6',                           // 현재가
    '.product-price strong',
    'span[class*="price"] strong',
    'meta[property="product:price:amount"]'
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      const text = sel.startsWith('meta')
        ? el.getAttribute('content')
        : el.textContent;
      const num = parseInt(text.replace(/[^0-9]/g, ''), 10);
      return isNaN(num) ? null : num;
    }
  }
  return null;
}

function extractOriginalPrice() {
  const selectors = [
    '._2MYJsEbmH9 del',                       // 원가 (취소선)
    '.product-price del',
    'del[class*="price"]'
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      const num = parseInt(el.textContent.replace(/[^0-9]/g, ''), 10);
      return isNaN(num) ? null : num;
    }
  }
  return null;
}

function extractDiscountRate() {
  const selectors = [
    '._2OXtA1swFh',                           // 할인율
    '.product-price .discount',
    'span[class*="discount"]'
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      const match = el.textContent.match(/(\d+)/);
      return match ? parseInt(match[1], 10) : null;
    }
  }
  return null;
}

function extractCategory() {
  // 빵부스러기(breadcrumb) 에서 카테고리 추출
  const breadcrumbs = document.querySelectorAll('.gnb_breadcrumb a, ._3Ea-sJfJPJ a');
  if (breadcrumbs.length > 0) {
    return Array.from(breadcrumbs).map(a => cleanText(a.textContent));
  }
  return null;
}

function extractShipping() {
  const result = { kind: null, amount: null, threshold: null };

  const shippingArea = document.querySelector(
    '.bd_2ATGH, ._2KaGFkS1bx, [class*="delivery"], [class*="shipping"]'
  );
  if (!shippingArea) return result;

  const text = shippingArea.textContent;

  if (text.includes('무료배송') || text.includes('무료')) {
    result.kind = 'free';
    result.amount = 0;
    // 조건부 무료 체크
    const thresholdMatch = text.match(/(\d[\d,]*)원\s*이상/);
    if (thresholdMatch) {
      result.kind = 'conditional';
      result.threshold = parseInt(thresholdMatch[1].replace(/,/g, ''), 10);
    }
  } else {
    const amountMatch = text.match(/배송비\s*(\d[\d,]*)원/);
    if (amountMatch) {
      result.kind = 'paid';
      result.amount = parseInt(amountMatch[1].replace(/,/g, ''), 10);
    }
  }

  return result;
}

function extractCoverImages() {
  // 상단 상품 이미지 슬라이더
  const selectors = [
    '._2GySGeMiaB img',                        // 메인 이미지 슬라이더
    '.product-thumb img',
    'img[class*="productImg"]',
    '.image_viewer img'
  ];

  for (const sel of selectors) {
    const imgs = document.querySelectorAll(sel);
    if (imgs.length > 0) {
      return Array.from(imgs)
        .map(img => getOriginalImageUrl(img.src))
        .filter(url => url && !url.includes('data:'));
    }
  }
  return [];
}

function extractDetailImages(maxCount) {
  // 상세 설명 영역의 이미지
  const detailSelectors = [
    '.se-main-container img',                  // 스마트에디터
    '._se_component_area img',
    '#DETAIL_SECTION img',
    '.product-detail img',
    'div[class*="detail"] img'
  ];

  let imgs = [];
  for (const sel of detailSelectors) {
    imgs = document.querySelectorAll(sel);
    if (imgs.length > 0) break;
  }

  if (imgs.length === 0) return [];

  return filterDetailImages(Array.from(imgs), maxCount);
}


// ──── "상세정보 더보기" 버튼 클릭 ────
async function expandDetailSection() {
  const moreButtonSelectors = [
    'a._3oDjSvLFlG[class*="more"]',
    'a.more_btn',
    'a._detail_more_btn',
    'button[class*="viewMore"]',
    'a[class*="viewMore"]'
  ];

  for (const sel of moreButtonSelectors) {
    const btn = document.querySelector(sel);
    if (btn) {
      btn.click();
      await sleep(1500);    // 상세 영역 로딩 대기
      return true;
    }
  }

  // 셀렉터로 못 찾으면 텍스트로 검색
  const allButtons = document.querySelectorAll('a, button');
  for (const btn of allButtons) {
    if (btn.textContent.includes('더보기') || btn.textContent.includes('상세정보')) {
      btn.click();
      await sleep(1500);
      return true;
    }
  }

  return false;  // 더보기 버튼 없음 (이미 펼쳐진 상태)
}


// ──── 옵션 추출 (드롭다운 순회) ────
async function extractOptions() {
  const options = [];

  // 옵션 셀렉트 박스 찾기
  const optionSelectors = [
    '._1iSa6NHnBk',                           // 옵션 영역
    '.product-option select',
    'select[class*="option"]',
    'div[class*="optionArea"]'
  ];

  let optionContainer = null;
  for (const sel of optionSelectors) {
    optionContainer = document.querySelector(sel);
    if (optionContainer) break;
  }

  if (!optionContainer) return options;

  // 방법 1: <select> 기반 옵션
  const selectEl = optionContainer.querySelector('select') || optionContainer;
  if (selectEl.tagName === 'SELECT') {
    const optionEls = selectEl.querySelectorAll('option');
    optionEls.forEach(opt => {
      if (opt.value && opt.value !== '*') {
        const text = cleanText(opt.textContent);
        const priceMatch = text.match(/[+\-]?\s*(\d[\d,]*)원/);
        options.push({
          name: text.replace(/[+\-]?\s*\d[\d,]*원/, '').trim(),
          price_diff: priceMatch ? parseInt(priceMatch[1].replace(/,/g, ''), 10) : 0,
          in_stock: !opt.disabled && !text.includes('품절')
        });
      }
    });
    return options;
  }

  // 방법 2: 커스텀 드롭다운 (클릭 기반)
  // 드롭다운 열기
  const trigger = optionContainer.querySelector(
    '[class*="select"], [class*="trigger"], [class*="btn"]'
  );
  if (trigger) {
    trigger.click();
    await sleep(500);

    const items = document.querySelectorAll(
      '[class*="optionItem"], [class*="option_item"], li[class*="opt"]'
    );

    items.forEach(item => {
      const text = cleanText(item.textContent);
      if (text) {
        const priceMatch = text.match(/[+\-]?\s*(\d[\d,]*)원/);
        options.push({
          name: text.replace(/[+\-]?\s*\d[\d,]*원/, '').trim(),
          price_diff: priceMatch ? parseInt(priceMatch[1].replace(/,/g, ''), 10) : 0,
          in_stock: !item.classList.toString().includes('sold') &&
                    !text.includes('품절')
        });
      }
    });

    // 드롭다운 닫기
    trigger.click();
  }

  return options;
}
```

**셀렉터 관련 중요 노트**:
- 네이버 스마트스토어는 클래스명이 빌드마다 바뀜 (난독화)
- 위 셀렉터는 2026-05 기준 — **주기적 업데이트 필요**
- 셀렉터 실패 시 폴백 전략: `meta[property="og:*"]` → 구조적 추출 → null 반환
- 셀렉터 변경 감지: 확장 popup에 "추출 실패율" 표시 → 사장님이 알림 받을 수 있음

---

## 7. 백엔드 API 변경

### 7.1 새 라우터: `backend/app/api/extension.py`

```
POST /api/ext/queue              작업 큐에 URL 배열 등록
GET  /api/ext/queue/next         확장에 다음 작업 1건 반환 (없으면 204)
POST /api/ext/result             확장에서 스크래핑 결과 수신
POST /api/ext/queue/complete     작업 완료 보고
GET  /api/ext/status             큐 현재 상태 (대시보드/morning report용)
```

### 7.2 큐 데이터 모델

```python
# backend/app/models/ext_queue.py

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class UrlStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"

@dataclass
class ScrapeJob:
    job_id: str                           # "2026-05-03_naver_detail"
    urls: list                            # [{ url, keyword_jp, keyword_kr }]
    config: dict                          # { delay_ms, extract_options, ... }
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = None
    # URL별 상태 추적
    url_statuses: dict = field(default_factory=dict)  # { url: UrlStatus }

# 인메모리 큐 (단일 사장님 사용이므로 충분)
# 향후 필요 시 DB 영구화 (task_manager 영구화와 같이)
scrape_queue: list[ScrapeJob] = []
```

### 7.3 API 엔드포인트 상세

```python
# POST /api/ext/queue — 작업 등록
# Request:
{
  "job_id": "2026-05-03_naver_detail",
  "urls": [
    {
      "url": "https://smartstore.naver.com/xxx/products/123",
      "keyword_jp": "美容液",
      "keyword_kr": "미용액"
    }
  ],
  "config": {
    "delay_ms": [3000, 5000],
    "extract_options": true,
    "extract_detail_images": true,
    "max_detail_images": 20
  }
}
# Response: { "job_id": "...", "total_urls": 40, "status": "pending" }


# GET /api/ext/queue/next — 확장이 다음 작업 요청
# Response 200:
{
  "job_id": "2026-05-03_naver_detail",
  "url": "https://smartstore.naver.com/xxx/products/123",
  "keyword_jp": "美容液",
  "keyword_kr": "미용액",
  "config": { ... },
  "index": 3,
  "total": 40
}
# Response 204: (대기 작업 없음)


# POST /api/ext/result — 스크래핑 결과 수신
# Request:
{
  "job_id": "...",
  "url": "https://smartstore.naver.com/xxx/products/123",
  "keyword_jp": "美容液",
  "keyword_kr": "미용액",
  "status": "success",
  "data": {
    "product_name": "메디큐브 AGE-R 부스터 프로",
    "brand": "메디큐브",
    "price": 45000,
    "original_price": 59000,
    "discount_rate": 24,
    "category": ["뷰티", "스킨케어", "에센스/세럼"],
    "options": [
      { "name": "단품", "price_diff": 0, "in_stock": true },
      { "name": "2개세트", "price_diff": 38000, "in_stock": true }
    ],
    "shipping": { "kind": "free", "amount": 0, "threshold": null },
    "cover_images": [
      "https://shop-phinf.pstatic.net/xxx/original.jpg"
    ],
    "detail_images": [
      {
        "url": "https://shop-phinf.pstatic.net/xxx/detail_1.jpg",
        "width": 860, "height": 1200,
        "position_ratio": 0.15,
        "index": 0,
        "aspect_ratio": 0.72
      }
    ],
    "extracted_at": "2026-05-03T01:15:30.123Z"
  }
}

# 백엔드 처리:
# 1. domestic_products 테이블 INSERT/UPDATE
# 2. cover_images → 이미지 다운로드 큐 (CDN 직접 fetch — 로그인 불필요)
# 3. detail_images → OCR 큐 (이미지 다운 → EasyOCR/Cloud Vision)
```

### 7.4 기존 코드 변경 매핑

```
기존 (naver_fetch_v2.py)                   변경 후
─────────────────────────────              ──────────────────
CDP 9222 connect                           → 삭제
playwright page.goto(url)                  → POST /api/ext/queue
page.wait_for_selector(...)                → 크롬 확장 content.js가 대기
page.evaluate("document.querySelector...") → content.js에서 추출
page.screenshot()                          → 삭제 (필요 시 확장에서)
NID_AUT/NID_SES 검사                       → 삭제
세션 만료 알림                              → 삭제

daily_workflow.py STEP 5:
  기존: await naver_fetch_v2(url)          → await queue_and_wait(urls)
  queue_and_wait():
    1. POST /api/ext/queue (URL 배열)
    2. 폴링: GET /api/ext/status (5초마다)
    3. 모든 URL 완료 시 return
    4. 타임아웃(30분) 초과 시 → 미완료 URL만 재큐잉 or 에러
```

### 7.5 새 클라이언트 모듈: `backend/app/services/ext_client.py`

naver_fetch_v2.py 를 대체하는 래퍼.

```python
# 기존 daily_workflow.py 에서:
#   result = await naver_fetch_v2(url, session)
# 변경 후:
#   result = await ext_client.fetch_product(url, keyword_jp, keyword_kr)

class ExtensionClient:
    """크롬 확장 프로그램을 통한 상품 데이터 수집 클라이언트"""

    async def fetch_products(self, items: list[dict], config: dict = None) -> list[dict]:
        """
        여러 URL을 크롬 확장 큐에 등록하고 결과를 대기.

        Args:
            items: [{ url, keyword_jp, keyword_kr }, ...]
            config: { delay_ms, extract_options, extract_detail_images, ... }

        Returns:
            [{ url, status, data }, ...]
        """
        job_id = f"{datetime.now().strftime('%Y-%m-%d')}_{uuid4().hex[:8]}"

        # 1. 큐 등록
        await self._post('/api/ext/queue', {
            'job_id': job_id,
            'urls': items,
            'config': config or DEFAULT_CONFIG
        })

        # 2. 완료 대기 (폴링)
        return await self._wait_for_completion(job_id, timeout_minutes=30)

    async def _wait_for_completion(self, job_id, timeout_minutes):
        """5초마다 상태 확인, 타임아웃 시 부분 결과 반환"""
        deadline = datetime.now() + timedelta(minutes=timeout_minutes)
        while datetime.now() < deadline:
            status = await self._get(f'/api/ext/status?job_id={job_id}')
            if status['status'] in ('completed', 'failed'):
                return status['results']
            await asyncio.sleep(5)
        raise TimeoutError(f"Extension job {job_id} timed out after {timeout_minutes}m")
```

---

## 8. 파이프라인 통합 — daily_workflow.py 변경

### 8.1 STEP 5 변경 (한국 상품 수집)

```python
# 기존 (R-6 이전, full 모드):
async def step5_domestic_products(keywords):
    for kw in keywords:
        # 네이버 쇼핑 API로 검색 (변경 없음)
        search_results = await naver_shopping_api.search(kw.keyword_kr)

        # 상세 수집 — 여기가 CDP → 확장으로 변경
        for product_url in search_results:
            # 기존: detail = await naver_fetch_v2(product_url)
            # 변경: 아래 batch 방식으로 교체
            pass

    # 변경 후: batch로 모아서 한번에 큐 등록
    all_items = []
    for kw in keywords:
        search_results = await naver_shopping_api.search(kw.keyword_kr)
        for url in search_results:
            all_items.append({
                'url': url,
                'keyword_jp': kw.keyword_jp,
                'keyword_kr': kw.keyword_kr
            })

    # 크롬 확장에 일괄 요청
    ext_client = ExtensionClient()
    results = await ext_client.fetch_products(all_items, config={
        'delay_ms': [3000, 5000],
        'extract_options': True,
        'extract_detail_images': True,
        'max_detail_images': 20
    })

    # 결과 → DB INSERT (기존 로직 유지)
    for r in results:
        if r['status'] == 'success':
            await save_domestic_product(r['data'])
```

### 8.2 UI 트리거 변경 (URL 재생성)

```
기존: SheetRowDetailPanel [URL 재생성]
      → POST /api/products/regenerate-content-from-url
      → naver_fetch_v2 (CDP)
      → OCR → SEO → JP detail

변경: SheetRowDetailPanel [URL 재생성]
      → POST /api/products/regenerate-content-from-url
      → POST /api/ext/queue (URL 1건)      ← 변경점
      → 크롬 확장이 수집
      → POST /api/ext/result → 백엔드 수신
      → OCR → SEO → JP detail              ← 변경 없음
```

사장님이 시트에서 [URL 재생성] 누르면, 크롬 확장이 백그라운드 탭에서 해당 URL을 열고 데이터를 수집합니다. 사장님은 기다리기만 하면 됩니다.

---

## 9. 에러 처리 + 복원력

### 9.1 확장 → 백엔드 통신 실패

```javascript
// background.js — 백엔드 연결 실패 시 재시도
async function fetchWithRetry(url, options, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      const res = await fetch(url, options);
      if (res.ok || res.status === 204) return res;
    } catch (e) {
      if (i === maxRetries - 1) throw e;
      await sleep(2000 * (i + 1));  // 2초, 4초, 6초
    }
  }
}
```

### 9.2 개별 URL 실패 → 스킵 + 계속

```
URL 40개 중 3개 실패 시:
  → 37개 성공 결과는 정상 처리
  → 3개 실패는 error 로그 + morning_report에 표시
  → 사장님이 수동 재시도 가능 (시트에서 해당 행 [URL 재생성])
```

### 9.3 확장 비활성 / Chrome 꺼짐 감지

```python
# backend — ext_client.py
# 큐 등록 후 60초 내에 첫 결과가 안 오면 → 확장 비활성 판단

async def _wait_for_completion(self, job_id, timeout_minutes):
    first_result_deadline = datetime.now() + timedelta(seconds=60)
    has_first_result = False

    while ...:
        status = await self._get(f'/api/ext/status?job_id={job_id}')

        if not has_first_result and status['completed_count'] > 0:
            has_first_result = True

        if not has_first_result and datetime.now() > first_result_deadline:
            # 텔레그램/슬랙 알림
            await notify("⚠️ 크롬 확장 응답 없음 — Chrome이 꺼져 있거나 확장이 비활성화됨")
            raise ExtensionInactiveError("No response from extension within 60s")

        ...
```

### 9.4 셀렉터 깨짐 감지

```javascript
// content.js — 추출 결과 검증
async function extractProductData(config) {
  const result = { ... };

  // 필수 필드 체크
  const missing = [];
  if (!result.product_name) missing.push('product_name');
  if (!result.price) missing.push('price');
  if (result.cover_images.length === 0) missing.push('cover_images');

  if (missing.length > 0) {
    result._warnings = {
      missing_fields: missing,
      message: '셀렉터 업데이트 필요 가능성 — 추출 실패 필드 있음',
      page_html_snippet: document.title  // 디버그용
    };
  }

  return result;
}
```

백엔드에서 `_warnings` 가 있는 결과가 일정 비율 이상이면 텔레그램 알림:
"⚠️ 스마트스토어 셀렉터 깨짐 의심 — product_name 추출 실패 15/40건"

---

## 10. popup.html — 상태 표시

```
┌─────────────────────────────┐
│  Qoo10 Helper               │
│                              │
│  상태: ● 작업 중             │
│  진행: 12 / 40              │
│  성공: 11  실패: 1           │
│  경과: 2분 30초              │
│                              │
│  [일시정지]  [중지]          │
│                              │
│  ─────────────────────────── │
│  최근 완료:                  │
│  ✅ 메디큐브 AGE-R (3.2초)   │
│  ✅ 달바 트러플 (2.8초)      │
│  ❌ xxx 상품 (타임아웃)      │
│                              │
│  백엔드: ● 연결됨            │
└─────────────────────────────┘
```

---

## 11. 설치 + 운영

### 11.1 초기 설치 (1회)

```
1. qoo10-helper-extension/ 폴더를 사장님 PC에 복사
2. Chrome → chrome://extensions → 개발자 모드 ON
3. "압축해제된 확장 프로그램을 로드합니다" → 폴더 선택
4. 확장 아이콘 고정 (핀)
5. 백엔드 시작 (기존 start.pyw)
6. 끝. 네이버 로그인 상태면 바로 동작
```

### 11.2 일상 운영

```
[출근]
  Chrome 열기 (확장 자동 활성화)
  → 백엔드 start.pyw (기존과 동일)
  → 확장이 5초마다 백엔드 폴링 시작
  → 작업 있으면 자동 처리

[야간 자동화]
  PC + Chrome 켜둔 상태 유지
  → 00:30 run_nightly.py → STEP 5에서 /api/ext/queue 등록
  → 확장이 자동 처리 → 결과 수신 → STEP 5.5+ 진행
  → 08:00 morning_report (기존과 동일)
```

### 11.3 업데이트

```
1. 파일 수정 (셀렉터 변경 등)
2. chrome://extensions → Qoo10 Helper → 새로고침 아이콘 (↻) 클릭
3. 끝 (Chrome 재시작 불필요)
```

---

## 12. 환경변수 변경

### 12.1 추가

```env
# .env 추가
EXT_QUEUE_POLL_TIMEOUT_SEC=60        # 확장 첫 응답 대기 (초)
EXT_JOB_TIMEOUT_MIN=30               # 전체 작업 타임아웃 (분)
EXT_DEFAULT_DELAY_MIN_MS=3000        # 페이지 간 최소 딜레이
EXT_DEFAULT_DELAY_MAX_MS=5000        # 페이지 간 최대 딜레이
EXT_MAX_DETAIL_IMAGES=20             # 상세 이미지 수집 최대 수
```

### 12.2 제거 가능

```env
# 크롬 확장 도입 후 불필요 (하위 호환용 유지 가능)
# NAVER_SESSION_WARN_DAYS=7
# NAVER_COOKIE_EXPIRY=...
# CDP_PORT=9222
```

---

## 13. 마이그레이션 계획

### Phase 1 — 확장 기본 (1~2일)

```
□ manifest.json + background.js + content.js 구현
□ 백엔드 /api/ext/* 라우터 추가
□ popup.html 상태 표시
□ 네이버 스마트스토어 셀렉터 검증 (샘플 10건)
□ 사장님 PC에 확장 설치 + 테스트
```

### Phase 2 — 파이프라인 연결 (1일)

```
□ ext_client.py 작성 (naver_fetch_v2 대체)
□ daily_workflow.py STEP 5 수정
□ regenerate-content-from-url API 수정
□ verify_run.py 에 확장 상태 체크 추가 (C7: ext 응답 확인)
□ 통합 테스트 (keyword_only → full 시뮬레이션)
```

### Phase 3 — 정리 (0.5일)

```
□ naver_fetch_v2.py 삭제 (또는 보관)
□ naver_session_check.py 삭제
□ CDP 관련 bat 파일 삭제
□ Qoo10ChromeDebug 스케줄러 task 삭제
□ STATUS.md 업데이트
□ morning_report에 확장 상태 추가
```

### Phase 4 — 안정화 후 full 모드 전환 (3~5일 운영 후)

```
□ keyword_only 모드에서 확장 경유 STEP 5 테스트 (수동 트리거)
□ 셀렉터 깨짐 빈도 모니터링
□ 안정 확인 후 AUTOMATION_MODE=full 전환
```

---

## 14. 향후 확장 가능성

```
Phase 5+ (필요 시):
  □ 네이버 브랜드스토어 셀렉터 추가 (content-scripts/naver-brand.js)
  □ 쿠팡 content.js 추가 (크롬 확장이면 쿠팡도 가능 — 봇 탐지 우회)
  □ 큐텐 JP 상세 수집 content.js (큐텐 cover_desc 강화)
  □ 이미지 선별 고도화: content.js에서 1차 분류 후 백엔드 비전 2차 분류
  □ 확장 popup → 미니 대시보드 (오늘 처리량, 에러율, 셀렉터 건강도)
```

---

## 15. 참고 — 네이버 스마트스토어 DOM 구조 (2026-05 기준)

```html
<!-- 상품명 -->
<h3 class="_3oDjSvLFlG">메디큐브 AGE-R 부스터 프로</h3>

<!-- 가격 -->
<span class="_2pgHN-ntx6">45,000원</span>
<del class="_2MYJsEbmH9">59,000원</del>

<!-- 커버 이미지 슬라이더 -->
<div class="_2GySGeMiaB">
  <img src="https://shop-phinf.pstatic.net/xxx?type=f860">
  <img src="https://shop-phinf.pstatic.net/yyy?type=f860">
</div>

<!-- 상세 영역 -->
<div class="se-main-container">
  <!-- "더보기" 클릭 후 펼쳐짐 -->
  <img src="https://shop-phinf.pstatic.net/detail_1.jpg">
  <img src="https://shop-phinf.pstatic.net/detail_2.jpg">
  ...
</div>
```

**⚠️ 주의: 위 클래스명은 네이버 빌드마다 바뀔 수 있음. 구현 시 다중 셀렉터 + 폴백 필수.**

---

**버전 히스토리**
- v1.1 (2026-05-02 후반): Phase 1+2 구현·검증 완료. 실제 차이점 추가 (16절).
- v1.0 (2026-05-02): 초기 설계. CDP→확장 전환 아키텍처, content.js 추출 로직, 백엔드 API, 마이그레이션 계획.

---

## 16. 실제 구현 차이 (v1.1 — Phase 1+2 검증 결과)

설계서 v1.0 가정 중 실제 구현에서 보정된 부분.

### 16.1 폴링 주기 (4.2절 보정)

| 설계 v1.0 | 실제 구현 |
|---|---|
| `chrome.alarms.create({periodInMinutes: 0.083})` ≈ 5초 | **1분** (Manifest V3 production minPeriod 제한) |
| `chrome.runtime.getPlatformInfo()` no-op keepalive | **`setInterval` 25초 + `chrome.storage.session.set({heartbeat})`** (작업 중에만) |

→ 즉시 트리거가 필요할 때는 popup 의 [즉시 폴링] 버튼.

### 16.2 content_scripts 자동 주입 회피 (3절 보정)

설계서: `content_scripts` 도메인 매치로 자동 주입 → 사장님 평소 보는 탭에도 주입됨.
실제: `manifest.json` 에 `content_scripts` 항목 제거 → `chrome.scripting.executeScript({files: [...]})` 으로 background 가 명시 주입. 사장님 평소 탭 오염 0.

### 16.3 isolated world 우회 (5~6절 보강)

설계서는 content.js 가 DOM querySelector + JSON.parse 로 추출. 실제로는:

- **`window.__PRELOADED_STATE__` 가 페이지의 진짜 페이로드** (Next.js `__NEXT_DATA__` 가 아님)
- content.js 는 **isolated world** 에서 동작 → 페이지의 `window` 객체 못 봄
- 해결: `chrome.scripting.executeScript({world: "MAIN", func: pageWorldDump})` 으로 페이지 world 에서 직접 dump 후 content.js 에 인자로 전달

### 16.4 background tab vs active tab (1절 보정)

설계서는 `chrome.tabs.create({active: false})` 만 사용. 실제 검증:

- **백그라운드 탭에서는 SPA hydration 진행 안 됨** → `__PRELOADED_STATE__.product` sub-store 빈 shell, JSON-LD 도 client-side 로 추가되는 시점에 배경 탭은 미반영
- 해결: `config.active_tab=true` 옵션 → `chrome.tabs.create({active: true})` → 작업 후 `chrome.tabs.update(prevActiveTabId, {active: true})` 으로 원래 탭 복원
- 사장님 화면 ~10초 깜빡임 (검증 OK)

### 16.5 Page world dump 의 polling (4.6절 보강)

```
chrome.scripting.executeScript({world: "MAIN", func: async pageWorldDump })
  → 함수 내부에서 isFilled() polling (max 25 attempts × 800ms ≈ 20s)
    → isFilled: ps.product/simpleProductForDetailPage 안 진짜 데이터 검사 (옵션/배송까지)
    → isMinimallyFilled: name/price 만 들어오면 true → 추가 5 attempts 후 dump
  → 채워지면 즉시 break + 400ms 추가 sleep → 최종 dump
```

### 16.6 Naver redux store 의 keyed-by-ID 패턴 (6절 신규)

```js
ps.product = { "A": {진짜 product 객체} }      // not ps.product 직접
ps.simpleProductForDetailPage = { "A": {...} }
ps.productDelivery = { "A": {...} }
```

`unwrap(sub)` 헬퍼로 `Object.values(sub)[0]` 추출 후 사용.

### 16.7 셀렉터 의존도 (5절 보정)

설계서: 다중 querySelector 폴백. 실제:

- product_name / price / cover_image / category 모두 **JSON-LD + `__PRELOADED_STATE__`** 로 잡힘 → DOM 의존 0
- detail_images 만 DOM 기반. 기존 셀렉터(`.se-main-container` 등) 대신 **모든 `<img>` 순회 + naturalWidth ≥ 600 + 페이지 위치 0.18~0.95 + exclude 패턴** 휴리스틱. 셀러별 다른 컨테이너 무관
- brand: JSON-LD → `__PRELOADED_STATE__.channel.channelName` → `page_title` 의 콜론 뒤 (3단계 폴백)

### 16.8 검증 결과 (5/2)

| 단계 | 추출 성공 |
|---|---|
| Phase 0 (backend `naver_fetch_v2`) | 0/5 (Naver 세션 false negative) |
| Phase 1 background tab | 0/5 (hydration 안 됨) |
| Phase 1 active tab + polling | **6/8 필드 100%** |
| Phase 2 e2e (시트 [URL 재생성]) | 정상 작동 (사장님 검증 완료) |

미해결: **options / shipping** — Naver SPA 가 client-side fetch 후 채우는 sub-store. polling 으로도 안 잡힘. 해결책: Naver smartstore API 직접 호출 (network 분석 필요, 1~3시간). 시트 수동 입력 흐름과 정합되어 미시급.

### 16.9 backend 통합 (8절 실제)

- `backend/app/services/ext_client.py` 신설 — `fetch_one(url)` 이 `naver_fetch_v2.fetch_naver_url_v2` 호환 dict 반환
- `backend/app/api/products.py` `_do_regenerate()` — 환경변수 `EXT_USE_EXTENSION` (기본 `true`) 으로 분기. `false` 시 레거시 흐름 (롤백용)
- 시트 [URL 재생성] 코드 변경 없음 — backend API 만 흐름 바뀜

### 16.10 정리 안 한 항목 (Phase 5 추후)

- `naver_fetch_v2.py` / `naver_session_check.py` 삭제 미진행 (env 토글로 fallback 보존)
- `data/naver-browser-profile/` 폴더 미삭제
- `automation/launch_chrome_debug.bat` 유지 (큐텐 STEP 3 / 쿠팡 captcha 용)
- `Qoo10ChromeDebug` 스케줄러 task 유지

R-8 안정 확인 후 Phase 5 정리.
