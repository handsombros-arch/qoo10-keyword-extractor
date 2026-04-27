# Phase 2 상세 스크래퍼 — 1차 시운전 (negative result)

**일시**: 2026-04-28 01:30
**관련 문서**: `docs/MASTER_SPEC.md` § 6 Phase 2

## 1. 목표 (MASTER_SPEC § 3.3 명세)

한국 상품 상세 페이지 진입으로 다음 동시 추출:
- 옵션별 가격 (옵션 셀렉트 클릭 → 가격 변동 캡처)
- 배송비 (무료/유료/조건부)
- 추가 이미지 (누끼 + 식품/화장품 내용물)

## 2. 구현 (G1~G3 완료)

### G1 DB 스키마
- ✅ `domestic_product_options` 테이블 신규 (id/dp_id/option_name/option_price_krw/in_stock/captured_at)
- ✅ `domestic_products` 컬럼 추가:
  - `shipping_kind` (free/paid/conditional/unknown)
  - `shipping_amount` (KRW)
  - `shipping_threshold` (조건부 무료 기준)
  - `detail_scraped_at` (DateTime)
  - `detail_image_paths` (Text JSON)

### G2 스크래퍼
- ✅ `backend/app/scrapers/m_domestic_details.py` 신규
- 쿠팡: Scrapling StealthyFetcher (camoufox stealth Firefox)
- 네이버: httpx best-effort (외부 셀러 사이트 다양)
- URL 호스트 자동 분기 (link.coupang.com → 쿠팡 처리)
- 배송비 정규식 (`parse_shipping`): 무료 키워드 + 「N원 이상 무료」 + 가격 패턴

### G3 엔드포인트 + 트리거
- ✅ `POST /api/products/domestic/scrape-details`
- ✅ `automation/trigger_domestic_details.py`
- 기본: `decision='accepted'` 케이스만 (광고 도용 페이지 진입 방지)

## 3. 시운전 결과 — **0/3 OK** ❌

### 시운전 1 (best-effort 모드, naver source)

| d= | URL 호스트 | 결과 |
|---|---|---|
| 4 | smartstore.naver.com | EMPTY (httpx GET 후 빈 파싱) |
| 14 | link.coupang.com | EMPTY |
| 58 | smartstore.naver.com | EMPTY |

→ httpx 만으로는 동적 페이지 컨텐츠 못 가져옴. 옵션/배송비/이미지 모두 0.

### 시운전 2 (URL 호스트 분기 패치, link.coupang.com → StealthyFetcher)

| d= | URL 호스트 | 결과 | 원인 |
|---|---|---|---|
| 14 | link.coupang.com | `fetch_error:AttributeError` | `css_first` 메서드 없음 (Scrapling Response API) — 패치 적용 |
| 1063 | smartstore.naver.com | `empty_parse` | httpx 한계 — JSON-LD 없음 |

### 시운전 3 (smartstore 직접 GET 분석)

```
GET https://smartstore.naver.com/main/products/12456101120
HTTP 429 (Too Many Requests)
JSON-LD 없음
```

→ 네이버 스마트스토어도 봇 차단 (429). httpx 단독으로 데이터 접근 불가.

### 시운전 4 (StealthyFetcher 로 link.coupang.com 직접 호출)

```
[INFO] Fetched (302) link.coupang.com → coupang.com/vp/products/...
[INFO] Fetched (403) coupang.com/vp/products/...
```

→ Scrapling StealthyFetcher 도 쿠팡 vp/products 페이지에서 **403 차단**. AKAMAI 가 검색 페이지보다 상세 페이지를 더 강하게 차단.

## 4. 진단

### 본질적 인프라 한계

| 셀러 | 차단 강도 | 1차 시도 결과 |
|---|---|---|
| 쿠팡 vp/products | **AKAMAI 403** | StealthyFetcher 도 막힘 |
| 쿠팡 검색결과 (m07) | 통과 | 검색은 OK, 상세는 차단 |
| 네이버 스마트스토어 | **429 Rate Limit** | httpx 막힘 |
| 네이버 검색 API (m08) | 통과 | API 는 OK |
| 외부 셀러 사이트 (다양) | 셀러별 다름 | 일반화 어려움 |

### 차단 비대칭성

검색 결과 페이지(m07/m08)는 통과되는데 상세 페이지는 차단 강함 — 봇 탐지가 상품 단위로 더 엄격. 단순 스크래핑 도구 (httpx, Scrapling) 만으로는 한계.

### 옵션 셀렉트 클릭 미구현

이번 1차 시운전은 옵션 클릭 없이 단일 가격만 시도. 옵션 클릭 + 가격 변동 캡처는 Playwright async 가 필요 — 동적 인터랙션 + DOM 변경 감지.

## 5. 다음 단계 옵션 (큰 작업)

### A. Playwright async 분기 (권장)
- `browser_manager` 에 별도 브라우저 컨텍스트 추가 (현재는 큐텐 1개만 운영)
- 쿠팡 vp/products: 헤드풀 + stealth 플러그인 (`playwright-stealth`)
- 네이버 스마트스토어: 헤드리스 + 모바일 User-Agent
- 옵션 셀렉트: `await page.locator(...).click()` 후 가격 영역 wait_for_change
- **예상 작업량**: 2~3일 (셀러별 DOM 처리 + 차단 회피 + 안정화)

### B. 모바일 API 역공학
- 네이버 스마트스토어: `https://smartstore.naver.com/i/v1/...` 같은 내부 API 분석 (모바일 앱 통신 분석)
- 쿠팡: 모바일 앱 API + 토큰 (위험: ToS 위반 가능)
- **예상 작업량**: 1~2일, 단 깨질 위험 큼

### C. 명세 축소 — 옵션 포기, 검색 API 데이터 활용
- 네이버 검색 API 가 이미 가격/링크 줌 (m08 결과)
- 추가 이미지/배송비/옵션 모두 포기
- 단점: 사장님 명세 (옵션별 가격 + 배송비 + 누끼/내용물) 핵심 미달

### D. Proxy 풀 + IP 회전
- 차단 회피용 — 비용 높음 (월 ~$50+)
- 안정성 낮음

## 6. 권장 (우선순위)

| # | 우선순위 | 액션 |
|---|---|---|
| 1 | ★★★ | **A 옵션 (Playwright async) 본격 진입** — 별도 세션에서 1~2일 집중 작업 |
| 2 | ★★ | A 진입 전, m07 (쿠팡 검색) 코드 재사용 가능성 검토 — 검색 결과 크롤링은 통과되니까 모듈 분리 유무 |
| 3 | ★ | C 옵션 (명세 축소) — A 가 막힐 때 폴백 |

## 7. 현재 인프라 잔존 가치

### 그대로 두어도 OK 한 부분

- ✅ DB 스키마 (`domestic_product_options` + 신규 컬럼) — Playwright 본격 진입 시 그대로 INSERT
- ✅ 엔드포인트 (`POST /api/products/domestic/scrape-details`) — 백그라운드 워커 + DB UPDATE 흐름 그대로
- ✅ 트리거 (`automation/trigger_domestic_details.py`) — CLI 그대로
- ✅ `parse_shipping` 정규식 — 어떤 소스에서 추출하든 재사용 가능
- ✅ URL 호스트 분기 — `link.coupang.com` 자동 라우팅

### 교체 필요한 부분

- ❌ `_stealth_fetch_coupang` — Playwright async 로 교체
- ❌ `_fetch_naver_detail` — Playwright 또는 모바일 API
- ❌ `_extract_coupang_detail` — DOM selector 새 버전 + 옵션 클릭 로직
- ❌ 옵션 클릭 시뮬레이션 — 신규 추가

## 8. MASTER_SPEC § 8 갱신 제안

```diff
- 4 | ★★★ | 한국 상품 옵션별 가격 스크래퍼 (Playwright 옵션 클릭 → DOM)
+ 4 | ★★★ | Phase 2 옵션 스크래퍼 — Playwright async 본격 진입 필요 (1~2일)
+      └ 인프라 (DB 스키마/엔드포인트/트리거/배송비 정규식) 완료. 셀러별 fetch+DOM 만 작업.
```

## 9. 결론

- **1차 시운전 결과**: 0/3 OK — httpx/StealthyFetcher 단독으론 한국 상품 상세 진입 차단됨
- **인프라는 완성** (DB/엔드포인트/트리거/정규식) — 후속 Playwright 작업이 그대로 활용 가능
- **다음 액션**: 별도 세션에서 Playwright async + 셀러별 fetch 정밀 작업
