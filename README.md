# Qoo10 키워드 추출기

큐텐 재팬(Qoo10.jp)에서 판매하는 셀러를 위한 키워드 리서치 / 상품 소싱 / 마진 계산 통합 도구.
원본은 VBA 매크로 엑셀 파일(`큐텐 키워드 추출기_v1.4.1b_Release_250628_엑셀버전.xlsm`)이며, 이를 **Python(FastAPI) + React** 웹앱으로 재구축한 버전이다.

CMD 창 없이 `start.pyw` 더블클릭 → `localhost:8000` 으로 접속하는 **로컬 실행형 웹앱** 이다.
서버리스(Vercel 등) 배포 불가 — Playwright headful 브라우저(눈에 보이는 실제 Chrome)가 필수 요건이라 데스크톱 환경에서만 동작한다.

---

## 1. 무슨 일을 하는가

큐텐 재팬에서 잘 팔리는 키워드와 상품을 자동으로 수집/분석해서, 어떤 상품을 어느 가격에 올리면 마진이 나올지를 한눈에 보여주는 도구. 14개의 화면(라우트)과 13개의 스크래퍼 모듈(M01~M13)로 구성된다.

### 주요 기능 (라우트별)

| 경로 | 설명 |
| --- | --- |
| `/` (Dashboard) | 통합 대시보드 — 작업 진행률, 최근 수집 통계 |
| `/keywords` | 트렌드 키워드 수집/조회 (M02 인기/일간/주간) |
| `/recommend` | 키워드 기반 상품 추천 (필터링 + 점수화) |
| `/recommend-products` | 엑셀형 상품 시트 — 마진 실시간 재계산, 샵 벤치마크 |
| `/insights` | 신규 키워드 / 변동 키워드 / 키워드 시계열 |
| `/competition` | 경쟁강도 분석 (M03) |
| `/bid` | 광고 경매 낙찰가 조회 (M04) |
| `/related-bulk` | 자동완성 / 연관 키워드 일괄 수집 (M05) |
| `/products` | 큐텐 / 쿠팡 / 네이버쇼핑 상품 검색 (M07~M09) |
| `/price-compare` | 한일 가격 비교 |
| `/tracking` | 내 상품 순위 추적 (M10) |
| `/bestsellers` | 큐텐 베스트셀러 모니터링 (M11) |
| `/image` | 상품 이미지 다운로드 |
| `/margin` | 마진 계산기 (단일 상품 상세) |

### 스크래퍼 모듈 (`backend/app/scrapers/`)

| 파일 | 역할 |
| --- | --- |
| `m01_login.py` | 큐텐 셀러관리(QSM) 로그인 |
| `m02_trend_keywords.py` | ADPlus 페이지의 인기/일간/주간 트렌드 키워드 (12개 카테고리) |
| `m03_competition.py` | 키워드별 경쟁강도(전체 상품수 / 주간 검색량) |
| `m04_bid_results.py` | 광고 입찰 낙찰 결과 (1~10위 가격) |
| `m05_related_keywords.py` | 큐텐 검색 연관 키워드 |
| `m07_coupang.py` | 쿠팡 상품 검색 — 한국 가격 비교용 |
| `m08_naver.py` | 네이버 쇼핑 상품 검색 |
| `m09_qoo10_products.py` | 큐텐 검색 결과 상품 목록 |
| `m10_ranking_tracker.py` | 등록한 상품의 검색 순위 추적 |
| `m11_bestsellers.py` | 큐텐 베스트셀러 페이지 |
| `m12_sales_volume.py` | 상품 판매량 추정 |
| `m13_shop_products.py` | 특정 샵(URL)의 상위 상품 — 벤치마킹용 |
| `autocomplete.py` | 큐텐 검색창 자동완성 키워드 |

---

## 2. 데이터 흐름

```
                ┌────────────────────────────────────────────────────────┐
                │ start.pyw  (더블클릭, CMD 없음)                          │
                │   uvicorn app.main:app  + 자동 브라우저 오픈              │
                └────────────────┬───────────────────────────────────────┘
                                 │
                ┌────────────────▼───────────────────────────────────────┐
                │ FastAPI (backend/app/main.py, port 8000)                │
                │   ─ /api/*          17개 라우터                          │
                │   ─ /assets, /*     frontend/dist 정적 서빙              │
                └────────────────┬───────────────────────────────────────┘
                                 │
        ┌────────────────────────┼─────────────────────────┐
        │                        │                         │
        ▼                        ▼                         ▼
 ┌──────────────┐       ┌──────────────────┐      ┌────────────────────┐
 │ BrowserMgr   │       │ TaskManager      │      │ SQLAlchemy 2.0     │
 │ (Playwright  │       │ (in-memory       │      │ async              │
 │  싱글톤,     │       │  task progress,  │      │  ─ Supabase        │
 │  headful     │       │  SSE 스트리밍)    │      │     Postgres       │
 │  Chrome)     │       │                  │      │     (asyncpg)      │
 └──────┬───────┘       └──────────────────┘      │  ─ 폴백 SQLite     │
        │                                          │     (aiosqlite)    │
        ▼                                          └─────────┬──────────┘
 ┌─────────────────────┐                                     │
 │ Scrapers M01~M13    │  ← 결과를 dict로 반환                │
 │ (Playwright DOM)    │                                     │
 └─────────┬───────────┘                                     │
           │ 외부 사이트 fetch                                │
           ▼                                                  │
 ┌─────────────────────────────────┐                          │
 │ qsm.qoo10.jp / qoo10.jp         │                          │
 │ coupang.com / shopping.naver    │  ↑ 결과 정제 후 DB 저장 ──┘
 │ translate.googleapis.com        │
 └─────────────────────────────────┘
                                                              │
                                                              ▼
                                                  ┌───────────────────────┐
                                                  │ React 19 + Vite SPA    │
                                                  │  ─ react-router-dom    │
                                                  │  ─ @tanstack/react-q   │
                                                  │  ─ ag-grid / recharts  │
                                                  │  ─ zustand (local 시트) │
                                                  │  ─ axios → /api        │
                                                  └───────────────────────┘
```

### 전형적인 시나리오: "키워드 수집 → 상품 추천 리포트"

1. 사용자가 `/keywords` 화면에서 카테고리 체크 후 **수집 시작** 클릭
2. `POST /api/keywords/trend` 호출 → `task_manager.create_task(...)` 로 마스터 태스크 생성
3. `asyncio.create_task(_task())` 로 백그라운드 실행. 즉시 `task_id` 만 반환
4. 백그라운드 태스크는 다음 순서로 진행:
   - `TrendKeywordScraper` 가 12개 카테고리를 차례로 돌며 100개씩 키워드 추출
   - `translate_batch` 로 일본어 → 한국어 일괄 번역 (구글 무료 endpoint)
   - 큐텐 검색 페이지에서 키워드별 전체/JP/KR/CN/OT 상품수 채우기
   - 경쟁강도 = 전체상품수 / 주간검색량 자동 계산
   - DB 저장 (날짜+카테고리+분류 조합으로 기존 행 삭제 후 적재)
   - 광고 경매 결과(M04) 자동 후속 수집
5. 프론트는 `useSSE` 훅으로 `/api/tasks/{task_id}/stream` 을 SSE로 구독하며 실시간 진행률 표시
6. `/recommend-products` 에서 관심 키워드 골라 **상품 수집** → 네이버+큐텐 동시 스크래핑
7. `marginCalc.ts` 가 클라이언트에서 실시간으로 마진율 계산하며 셀 편집 가능 (localStorage 저장)

### 인증/세션

- 첫 실행 시 `start.pyw` 가 백그라운드에서 `auto_login_on_startup()` 실행
- 쿠키(`backend/data/session/cookies.json`) 가 있으면 → 그대로 복원
- 만료됐고 자격정보(`credentials.json`) 도 저장돼 있으면 → ID/PW 자동 입력 + 로그인 버튼 클릭
- 캡차가 뜨면 사용자 수동 완료 대기 (브라우저 창은 열려 있음)

### DB 스키마 (`backend/app/db/models.py`)

| 테이블 | 용도 |
| --- | --- |
| `keywords` | 키워드 본체 (검색량, 카테고리, 경쟁강도, 국가별 상품수) |
| `volume_history` | 검색량 일별 스냅샷 |
| `bid_history` | 광고 경매 낙찰가 (1~10위) |
| `tracking_items` / `tracking_history` | 내 상품 순위 추적 |
| `qoo10_products` | 큐텐 검색 결과 상품 |
| `domestic_products` | 쿠팡/네이버 상품 (한국 가격) |
| `bestseller_items` | 베스트셀러 |
| `user_data` | 범용 JSON 저장소 (시트, 관심 키워드, 샵 캐시 등 PC 간 공유용) |

연결 URL은 `backend/.env` 의 `DATABASE_URL` 만 바꾸면 SQLite ↔ Postgres 자동 분기 (`config.py` 에서 `postgresql://` → `postgresql+asyncpg://` 자동 변환).

---

## 3. 기술 스택

### Backend (`backend/`)

- **Python 3.10**
- **FastAPI 0.115** — 17개 API 라우터, lifespan으로 DB 테이블 자동 생성
- **uvicorn 0.30** — ASGI 서버 (Windows 에서는 `WindowsProactorEventLoopPolicy` 명시)
- **Playwright 1.48** — headful Chromium / 시스템 Chrome 우선 사용, `disable-blink-features=AutomationControlled` 옵션
- **SQLAlchemy 2.0** (async) + `aiosqlite` / `asyncpg` — 동일 코드로 SQLite/Postgres 모두 지원
- **sse-starlette** — 작업 진행률 SSE 스트리밍
- **httpx** — 구글 번역 비공식 endpoint 호출
- **openpyxl** — 큐텐 대량등록 엑셀 템플릿(`qoo10_template.xlsx`) 채우기
- **pydantic 2.9** — 요청/응답 스키마

### Frontend (`frontend/`)

- **React 19** + **TypeScript ~6.0** + **Vite 8** + **Tailwind CSS 4**
- **react-router-dom 7** — 14개 라우트
- **@tanstack/react-query 5** — 서버 상태 캐시
- **@tanstack/react-table 8** + **ag-grid 35** — 표 (대용량/엑셀형 양쪽)
- **recharts 3** — 시계열 차트
- **zustand 5** — 클라이언트 상태 (`productSheet`, `interestKeywords`, `shopCache`, `cloudSync` 4개 스토어)
- **axios** — `/api` 프록시 (vite dev) 또는 동일 호스트 (prod)

### 외부 의존성

- 시스템 Chrome (있으면 우선 사용, 없으면 Playwright 번들 Chromium)
- 구글 번역 무료 endpoint (`translate.googleapis.com/translate_a/single`) — API 키 불필요
- Supabase (선택, Postgres) — 두 PC 간 DB 공유 용도

---

## 4. 디렉토리 구조

```
qoo10-keyword-extractor/
├─ start.pyw              # 더블클릭 진입점 (CMD 없이 백엔드+브라우저)
├─ start.bat              # 대안 (CMD 보임)
├─ SETUP.md               # 두 PC 셋업 가이드 (Supabase, .env, 마이그레이션)
├─ 큐텐 키워드 추출기_v1.4.1b...xlsm  # 원본 VBA (참고용)
│
├─ backend/
│  ├─ requirements.txt
│  ├─ .env.example        # DATABASE_URL 양식
│  └─ app/
│     ├─ main.py          # FastAPI 엔트리, 라우터 등록, 정적 서빙
│     ├─ config.py        # Settings (DATABASE_URL 자동 변환 포함)
│     ├─ api/             # 17개 라우터 (auth, keywords, bid, products, ...)
│     ├─ scrapers/        # M01~M13 + autocomplete
│     ├─ services/        # task_manager, auto_login, translation,
│     │                   #   margin_calculator, qoo10_export, exchange_rate
│     ├─ browser/         # BrowserManager 싱글톤 (Playwright 컨텍스트 관리)
│     ├─ db/
│     │  ├─ models.py     # 9개 테이블
│     │  ├─ connection.py # async engine (Postgres pool / SQLite 분기)
│     │  ├─ base.py       # Repository 추상 인터페이스
│     │  └─ sqlite_repo.py# SQLAlchemy 구현 (이름은 sqlite지만 Postgres에도 사용)
│     ├─ schemas/         # Pydantic 요청/응답
│     └─ data/
│        ├─ qoo10_shipping_rates.json  # 큐텐 KSE/Tracx 배송비 테이블
│        └─ qoo10_template.xlsx        # 대량등록 엑셀 양식
│  └─ scripts/            # 일회성 스크립트 (SQLite→Postgres 마이그레이션 등)
│
└─ frontend/
   ├─ vite.config.ts      # /api → :8000 dev 프록시
   ├─ src/
   │  ├─ App.tsx          # 라우터 + QueryClientProvider
   │  ├─ pages/           # 14개 페이지
   │  ├─ components/
   │  │  ├─ Layout/       # MainLayout, Sidebar, Header
   │  │  ├─ Grid/         # ag-grid 래퍼
   │  │  └─ common/
   │  ├─ api/             # client.ts (axios), endpoints.ts (모든 API 호출 함수)
   │  ├─ hooks/useSSE.ts  # 작업 진행률 SSE 구독
   │  ├─ store/           # zustand 4개 (시트/관심/샵/클라우드)
   │  ├─ lib/marginCalc.ts# 클라이언트 사이드 마진 재계산
   │  └─ types/index.ts
   └─ dist/               # `npm run build` 산출물 → 백엔드가 정적 서빙
```

---

## 5. 마진 계산 로직 (`services/margin_calculator.py`)

원본 엑셀의 "이중 환율" 방식을 그대로 재현한다 (이익은 ×10 대략환율, 마진율은 ×9.5 정확환율).

비즈니스 규칙:
- **판매가 < 20,000원 → 유료배송 (Tracx, 바이어 부담)**
- **판매가 ≥ 20,000원 → 무료배송 (KSE, 셀러 부담)** — `shipping_mode="auto"` 가 자동 적용
- 마진이 부족하면 `analyze_compositions` 가 **2개·3개 세트 구성** 을 제안 (배송비 규모 효과)

상수:
- `QOO10_COMMISSION_RATE = 0.135` (13.5%)
- `MEGAWARI_DISCOUNT = 0.9` (메가와리 할인 적용 시)
- `FREE_SHIPPING_THRESHOLD_KRW = 20000`

---

## 6. 실행 방법

상세 셋업은 [SETUP.md](./SETUP.md) 참고.

### 빠른 실행 (이미 설치 완료된 PC)

```
start.pyw 더블클릭
→ http://localhost:8000 자동 오픈
```

### 최초 설치

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env       # DATABASE_URL 입력

# Frontend
cd ..\frontend
npm install
npm run build                # → frontend/dist (백엔드가 서빙)
```

개발 모드 (HMR):
```bash
# 터미널 1
cd backend && .venv\Scripts\activate && uvicorn app.main:app --reload

# 터미널 2
cd frontend && npm run dev   # localhost:5173, /api 는 :8000으로 프록시
```

---

## 7. 두 PC 동기화 모델

- **코드**: GitHub (`handsombros-arch/qoo10-keyword-extractor`, private)
- **DB**: Supabase Postgres (서울 리전, 풀러 :5432) — 키워드/상품/시트가 자동 공유
- **세션 쿠키**: PC 로컬 (`.gitignore` 처리) — PC마다 큐텐에 따로 로그인
- **시트/관심키워드**: `user_data` 테이블 + `cloudSync.ts` 가 양방향 동기화

`backend/.env` 의 `DATABASE_URL` 을 비우면 폴백으로 로컬 SQLite (`backend/data/qoo10.db`) 가 사용된다.
