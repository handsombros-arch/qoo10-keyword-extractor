---
name: project_lv10_reset
description: 엘비텐(LV10) 재정비 — 프로그램명 변경(6/3) + 목적 재정의 + 중복/미작동 기능 정리 + 맥북 24h 서버화. 키워드 데이터 절대 삭제 금지(큐텐 복구 불가).
metadata: 
  node_type: memory
  type: project
  originSessionId: e1b20f16-d8fb-401d-b867-033623a47421
---

**2026-06-03 시작.** 구 "Qoo10 키워드 추출기" → **엘비텐 (LV10)** 으로 리브랜딩(커밋 4e47570, ab8c185: 사이드바/헤더/탭제목/런처/확장/README/STATUS). 마켓플레이스 지칭 "큐텐/Qoo10" 표현은 유지.

## 사장님 지시 (전략 리셋)
"중복·불필요·미작동 기능·로직이 너무 많다. **프로그램 목적을 다시 정리**하고, 그 기준으로 제거·수정해 나간다. 하나씩 정리."

## 🔴 절대 제약 — 키워드 데이터 삭제 금지
**큐텐은 크롤링 이후 과거 일자 데이터 복구 불가.** 누적 키워드 데이터(Supabase `keywords`/`volume_history`/`bid_history`)는 절대 소실 금지.

### 실측된 위험 코드 (정리 0순위)
- `backend/app/db/sqlite_repo.py:30` `save_keywords` — `(lookup_date, category, classification)` 조합별 **기존 행 전부 delete 후 재적재**. 재크롤이 부분/0건이면 과거 일자 양호 데이터가 파괴됨. (의도: rank 31~100 잔재 제거였으나 데이터 소실 위험)
- `delete_by_date(lookup_date)` (sqlite_repo.py:97) + `DELETE /keywords/by-date/{date}` + `POST /keywords/_delete_all`(R-7) — 위험 엔드포인트.
- **대책 방향**: delete-before-insert → upsert((date,keyword) 기준) 또는 "신규 batch 비었거나 행수 급감 시 삭제 스킵" 가드. 위험 엔드포인트 봉인/확인절차.
- 안심: 데이터는 Supabase **클라우드**에 있어 로컬 코드 정리 자체는 DB 안 건드림. 위험은 위 write 경로뿐.

## 새 자산 — 맥북 24h 서버
사장님: "로컬 AI 못 돌리는 맥북 하나 생김. 서버용으로 24h 켜두고 매일 자동 실행 방법 고민." (= [[project_qoo10_no_api_roadmap]] 의 Intel MBP conductor 구상 부활)
- 맥북 = ollama/비전 불가(Intel, GPU 없음). 가능: FastAPI 백엔드 + 스케줄러(launchd) + Playwright/크롬확장(디스플레이 있음).
- AI 무거운 단계는 ① LLM 호출 캐시/규칙화로 제거 후 맥북 단독, 또는 ② 메인 PC(RTX 5080) wake-on-LAN로 위임. **6/3 사장님 결정: 경로 C 하이브리드** (평소 맥북 단독 캐시적중, 캐시미스·이미지매칭만 메인PC 위임).
- **목적 정의 6/3 확정**(잠정): "큐텐 재팬에서 팔릴 한국 상품을 마진까지 계산해 시트로 뽑아주는 도구" — 키워드 누적→추천→한국매칭→마진시트→검수. 이 문장 밖 기능은 정리 대상.
- **🔄 6/4 리뉴얼 흐름(사장님 제공, 이전 목적 확장·대체)** → 상세 `docs/엘비텐_로직_정리.md`. **핵심 사이클 vs 부수** 구분:
  - 핵심 지표 = 수요·한국비중·경쟁강도 + **경매 낙찰가/구좌(광고슬롯)** (매우 중요). 키워드 선별 = "경쟁 낮음"만 아니라 **"노출 잡을 수 있나(구좌 열림)"** 중심 — 붐벼도/낙찰없어도 구좌 있으면 진입 OK. 기본 카테고리=**뷰티/식품**.
  - 핵심 사이클(반복): ①키워드 찾기 ②한국 소싱 마진비교(계산기) ③등록-SEO(연관검색어→태그, 상품명=상품명+USP+연관검) ④등록-상세(이미지+AI+피그마) ⑤**노출-광고최적화(스마트세일즈CPS→플러스전시CPT→파워랭크업, 순위추적으로 광고%↔순위 피드백)** ⑥배송(배대지) ⑦CS(나중, API희망).
  - **순위추적 = 핵심 도구로 승격**(5단계 광고 피드백) → UI 노출 우선순위↑(이전 "나중에"에서 격상).
  - 부수: 올영(브랜드/상품명→일본어 번역→큐텐 역검색·연관검), 샵 벤치마킹(URL→잘팔리는상품/브랜드/리뷰/가격/배송비).
  - 외부 의존: 큐텐 광고콘솔(집행)·피그마(상세)·배대지(배송)·AI이미지.
- **🤖 자동화 범위 확정(6/4)**: 사장님 "억지 자동화 안 함. 단 24h 구형 맥북 있으니 **키워드 RD 추출 + 입찰가(낙찰가) 추출만 매일 자동**으로 들어오면 좋겠음." **이유: 당일 안 뽑으면 다음날 못 뽑음**(큐텐 일자 데이터 복구 불가). → 자동화 대상 = **M02 트렌드 키워드 + M04 낙찰가, 매일 1회, 맥북에서.** 나머지(소싱·SEO·광고·배송)는 전부 수동. (분류 등 AI는 맥북서 불가 — 키워드+낙찰 수집은 스크래퍼라 AI 불필요, 맥북 가능.)
  - ⚠️ **선행 필수 = 데이터 안전가드**: 매일 자동수집이 부분/0건 실패하면 save_keywords가 오늘 데이터 덮어씀(4/30 0건 사고가 자동이면 데이터 자동 파괴) → 가드 먼저 박은 뒤 자동화 켜야 안전.
  - 맥북 셋업(별도 기기): repo clone + Python/Playwright/Chrome + 큐텐 로그인 + launchd 일일 스케줄. 로직(가드+일일 키워드/낙찰 잡)은 여기(Windows)서 만들어 git/Supabase 공유, 맥북이 pull해 실행.
  - **텔레그램 알럿(6/4)**: Hermes=텔레그램 봇으로 돎. 원하는 건 "수집 완료 여부 체크"(현 슬랙처럼). **맨 마지막 작업으로 보류**(엘비텐 이미 슬랙 알림 있어 텔레그램 채널 추가는 소작업, ③ 맥북 끝에).

## ✅ 자동화 ①② 완료 (6/4)
- **① 데이터 안전가드 완료·검증(커밋 a4068be)**: `save_keywords` — 조합별 새행수 < 기존×0.5면 삭제·적재 스킵(기존보존)+경고. `KEYWORD_SAVE_GUARD_RATIO` env. 검증: 10개→3개 재수집 시 10 보존, 8개 시 정상갱신. 의도적 삭제(by-date/_delete_all)는 유지. **매일 자동수집 안전 전제 충족.**
- **② 일일 잡 빌드(커밋 abe99f5)**: `automation/trigger_daily_rd.py` — `/api/keywords/trend`에 뷰티(3)+식품(7)+collect_bids 요청+폴링. `--olive`로 올영 같이, `--no-bids`, `--cats`. 백엔드 실행+큐텐 로그인 전제. (아직 실가동 미테스트 — 무겁고 오늘 데이터 재수집이라.)
- **③ 남음 = 맥북 셋업**(별도기기 launchd 스케줄+백엔드 상주+로그인) **+ ④ 텔레그램 알럿(맨 마지막)**.
- 사장님이 별도 **벤치마킹 프로그램 폴더**를 줄 예정 → 분석 후 논의 (구현 참고용).

## 벤치 분석 (6/3) — `큐텐 분석기 (벤치)/`
원본 상용 VBA 도구 2종. olevba 로 VBA 추출 (`C:\Users\Admin\price_vba.txt`, `keyword_vba.txt`).
- `큐텐 키워드 추출기 v1.4.3`(260208) = 엘비텐 원본의 최신판.
- **`큐텐 가격 최적화 도우미 v1.1.0b`**(260204) = 사장님 구현 희망 대상. **엘비텐과 목적 다름**: 발굴이 아니라 **등록 상품 가격 재책정**.
  - **핵심1 메가와리 판매가 역산**(M03 `AdjustPriceToTarget`): 실효부담률 `0.112`(수수료10%+할인후1.5%). 사용자 "평상시대비 마진%" 입력 → `메가판매가=ROUNDUP(판매가×(입력%/100÷0.888),10엔)`.
  - **핵심2 환율 대응 재책정**(`AdjustPriceToExchangeRate`, 26.02.03): `판매가×기준환율/적용환율`.
  - **핵심3 무게기반 배송비 최적화**(M04): 큐텐 배송비=무게구간 연동 → 등록무게 조정 + 계정/코드별 수수료테이블(`GetFeeFromTable`).
  - 부가: **Nanobanana=Gemini 2.5 Flash Image** 상품이미지 생성 (⚠️No-API 충돌 + VBA에 Gemini 키 하드코딩 노출).
  - 작동: QSM 상품목록 엑셀 다운 → 재계산 → 파일저장 → 수동 재업로드. Selenium+machineID 라이선스.
- **논의중**: 가격최적화를 엘비텐에 흡수(기존 마진계산기/시트에 컬럼·버튼으로) vs 별도. 목적정의에 "가격관리" 추가 여부. Gemini 이미지생성 포함 여부(No-API 예외).

## 🔑 핵심 진단 (6/3) — "기능은 많은데 활용도 떨어짐"의 정체
사장님 직감: 원본 대비 엘비텐 기능 많은데 실제 활용도 낮음. 코드 검증 결과 = **"기능 추가"가 아니라 "있는 기능을 핵심 루프에 연결+완결"이 과제.**
- **원본 강점**: 시트 1장 + 버튼 1줄, 순서대로 클릭→같은 표 누적→결과물=업로드용 엑셀. 한 바퀴가 끝까지 돈다. 환율도 수집 때마다 자동 반영.
- **엘비텐 3대 구조병**: ①분산(14라우트, 1작업에 화면 여러개) ②**미연결(핵심병)** ③반쯤죽음(orphan6/M12죽음/자동화OFF).
- **스모킹건=실시간 환율**: `get_exchange_rate()`(Dunamu 라이브) **존재하지만** 마진계산기는 `9.5` 고정/수동입력(`marginCalc.ts`, `margin_calculator.py:103`, `CompositionsPanel.tsx`). 라이브 환율은 orphan `/price-compare`·`/utils`에서만 호출. = "만들어놓고 메인 흐름에 안 꽂음"의 표본.
- 같은 미연결 패턴: LLM 캐시(자리만), 옵션/배송 수집(봇차단 off).
- **방향**: 원본식 "한 흐름으로 끝까지 도는 완결 루프" 복원. 사장님 needs=**실시간 환율을 마진계산에 연결**(신규개발 아니라 연결작업: 9.5기본→라이브, 시트/추천에 자동주입, 화면에 오늘환율 표시+하루1회 캐시).

## 🎯 미연결 전수감사 (6/3, ①단계) — 완결 루프 설계도
**최대 발견: 루프가 절반만 살아있음.** `AUTOMATION_MODE="keyword_only"`(R-6) → 발굴✅·분류✅ / **한국매칭❌·마진시트❌·검수❌ (STEP5~7 통째 스킵)**. 그래서 매일아침 추천상품 0개. 키워드만 쌓이고 "뭘 팔지" 산출물 없음. 끈 이유=한국매칭/이미지매칭/옵션·배송 불안정.
- 여파: 쓰고 안 읽는 데이터 대량 — set_count 기본값1 고정(마진왜곡), shipping unknown(마진+3~5%부풀림), DomesticMatchCandidate 0건.

### 미연결 3분류
- **🗑️제거안전**: m12_sales_volume / orphan 6페이지 / 죽은 API래퍼(getExchangeRate 프론트미호출·searchCoupang·searchNaver) / orphan엔드포인트(naver_session_check·login_setup·single_url_fetch·evaluate_extras) / 쓰고안읽는 컬럼 6종(volume_change_flag·classification·index_key·set_count_vision·image_score_json·weight_source). ※keywords 데이터 자체는 불간섭.
- **🔌연결필요**: 실시간환율→마진계산(프론트 API조차 미호출, 9.5고정) / LLM캐시 3종(category·brand_expand·image_match) / category_inferred UI미활용.
- **⚖️의사결정**: STEP5~7 재가동 vs 루프 재설계.

### 완결 루프 모양 — 3후보 (사장님 결정 대기)
- A 완전자동 복원: STEP5~7 재가동+불안정점(이미지매칭/배송/옵션) 수리. 활용도 최대지만 난이도 높음(minicpm 약점·봇차단).
- **B 반자동(추천)**: 발굴·환율·마진·세트수만 자동완결, 한국 소싱매칭은 사장님 수동. AI매칭 불안정 회피, 즉효. 원본+가격최적화 철학에 부합.
- C 하이브리드: B 기본 + 이미지매칭은 "보조 후보 제안"만(자동결정X).

## 6/3 확정 — B 반자동 채택 + 후속 결정
사장님: **B 반자동 채택**. 루프 모양 먼저 확정 후 제거/연결 착수.
- **B 루프**: [야간자동] 1발굴(누적·소실금지)→2분류(+캐시)→3필터→4환율확보 ⇒ "오늘의 후보 키워드 시트". [낮 수동] 5소싱(한국상품 검색·시트에 붙임, 크롬확장 경유)→6입력(가격/무게/세트수, set_count 보조)→7마진(실시간환율+수수료+배송비 자동계산→체크→큐텐export).
- **빠지는 기능 = 비활성 확정**: 자동 이미지매칭(STEP5.95)·검수페이지(/review)·자동상세(옵션/배송 수집)·auto-build·match_retry·auto_learning. 사장님 "모두 비활성 OK".
- **무거움 체크 결과**: 비활성만으로 런타임 부담 0 (keyword_only로 미실행 + easyocr/vision은 lazy import). 무거워지는 건 코드 가독성 + 맥북이전 시 torch/easyocr/vision 의존성. → **지금 비활성, 맥북 이전 직전 제거**. B가 비전 빼므로 맥북(비전 불가)과 정합.
- **연관검색어 강화(step5)**: 엘비텐 `/related-bulk`(RelatedBulkPage)가 이미 **원본보다 많은 10+ 소스** 보유(큐텐 광고연관/자동완성/연관, 아마존JP, 야후JP/야후쇼핑, 라쿠텐, 핫코, KeywordTool) — **그러나 대부분 off + 더보기메뉴에 묻혀 단절**. "강화"=신규개발 아니라 ①step5에 통합 ②좋은소스 활성+검증 ③원본 M06식 seed입력→다중소스종합 UX. (원본 JS_관련키워드=JungleScout 유료API·인도용→No-API 제외).
- **용어**: M02=큐텐 ADPlus 트렌드 키워드 수집기(발굴 엔진). set_count=묶음개수(단가=가격÷set_count, 가짜마진 방지).
## ✅ 필터 직관화 — 존 모델 확정 (6/3)
구 필터(경쟁강도≤2.0+한국비율≥0.3+검색량≥40, 비직관·통과못하면 데이터 숨김) 폐기 → **존 라벨링 모델**(버리지 않고 딱지만 붙임 = 데이터보존+활용도↑).
- **존(2축: 검색수 50 / 상품수 200)**: 검색≥50&상품≤200=🟡**황금존**(핵심타겟) / 검색≥50&상품>200=🔴**레드오션** / 검색<50&상품≤200=⚫**데드존** / 검색<50&상품>200=🟤**포화**(강조 없음, 별도표시 X 가능).
- **경쟁강도**(=total_products/search_volume_weekly, 이미 계산됨) = **별개 보조지표**, 황금존 내 정렬용(낮을수록 위).
- **시계열 라벨(존과 독립, 중첩가능)**: 🆕**신규**=과거 VolumeHistory 기록 없이 이번 첫 등장 / 📈**상승**=직전 수집 스냅샷 대비 search_volume_weekly **+20%↑**(현재 검색수≥30 노이즈컷). 비교기준=직전 수집(불규칙 수집 때문에 "전날/N일전" 대신 "직전 스냅샷").
- **데이터 매핑**: 검색수=`search_volume_weekly`, 상품수=`total_products`, 경쟁강도=`competition_intensity`. 임계값(50/200/+20%/30)은 `/settings` 슬라이더 조정.
- **🔑 신규/상승 이미 계산됨(미연결)**: `insights.py`(최신 vs N일전 검색량/순위 변화 Top 상승/하락) + `keywords.py`(신규=lookup_date 첫등장) 이미 존재하나 `/insights`(더보기)에 갇힘. 원본도 "전날대비검색량증감유무" 보유. `volume_change_flag` 컬럼 비어있음→계산 라벨 저장처로 재활용. → **새로 만들 것 거의 없음, 존 화면에 연결만**.
- **다음**: 존 분류 로직 + UI(존 뱃지·색·필터/정렬) 설계.

### 🎯 "좋은 키워드" 기준 리뉴얼 (6/4)
- **메인**: 🟡황금존(경쟁강도 낮음, 기존 유지). **한국비율(products_kr/total)=보류**(사장님도 미정, display만 게이트X).
- **서브**: **구좌 열림 = 낙찰수(bid_count) ≤ 3** (들어가면 바로 상위 노출, "매우 중요") / 🆕**NEW**=전일·전주 대비 첫 등장(단일 라벨).
- **중복 우려 해법(사장님 "고민")**: ~~키워드당 1행 통합~~ → **6/4 사장님 통찰로 폐기**. ① 같은 키워드라도 **카테고리·분류(주간/주요/일간/연관…)가 다르면 당연히 별개 행**(합치면 안 됨). ② 진짜 중복은 **(키워드+카테고리+분류) 동일 + 조회날짜만 다른** 행(매일 수집 누적, 의도된 시계열 보존). 실측: 8,909행 / 고유조합 2,248 / 예시 カラコン·アヌア美容液 등 17일치=17행. ③ **그러나 RD 기본뷰가 이미 '최신 1일'(날짜UI 작업)이라 하루만 보면 과거행 안 뜸 → 날짜중복 이미 해결**. → **행 통합 작업 불필요(폐기).**
- **Phase 2 축소 확정(6/4)**: 행 통합 버림. **남는 건 NEW/상승 뱃지뿐** — 행 합치기 아니라, 오늘 하루치 화면의 각 키워드에 전일/전주 대비 첫등장(NEW)·직전대비+20%(상승) 뱃지만 표시(과거 비교는 백그라운드). insights.py·keywords.py·volume_change_flag 활용.

## ✅ "좋은 키워드" 화면 Phase 1 + 옛 추천/필터 정리 (6/4)
- **Phase 1 완료**(커밋 7effbcb): KeywordPage에 **존 컬럼**(황금존/레드오션/데드존/포화, 검색50·상품200, 색상) + **구좌 컬럼**(낙찰수≤3=열림) + 빠른필터(존별/구좌/**⭐좋은키워드**=황금존+구좌). 프론트 계산. Phase 2(NEW/상승+키워드당1행)=백엔드 시계열 후속.
- **옛 로직 제거**(사장님 "헷갈림 빼고 정리"): ①역직구 추천점수(d4a6075) ②**역직구 추천 페이지 통째**(5ef1738: 라우트·사이드바·파일·링크. 관심키워드 북마크는 유지=상품시트가 사용, 깨질링크→/keywords) ③/settings 자동필터 임계값(0be89ed: 경쟁강도/한국비율/검색량 UI+상태+로드저장+타입). 
- 백엔드 auto_filter 엔드포인트는 잔존(야간 비활성 흐름용)→존 모델이 선별 대체. 추후 정리.

## ✅ 중복 시트 정리 — 조사 결과 (6/4)
- **키워드 데이터가 3화면 중복**: 역직구추천(RecommendPage, 1200줄)·키워드추출RD(KeywordPage, 660줄)·시계열인사이트(InsightsPage) — 모두 `keywords` 테이블을 제각각 표로 렌더. = 사장님 "동일 엑셀 너무 많다"의 정체.
- 상품시트(RecommendProductsPage, 3192줄)는 1개지만 **시트 입력경로 3개**(키워드추출/추천/검수). 검수(ReviewPage)=자동검수 결과인데 **B반자동선 자동검수 비활성→역할 거의 없음**(통합/제거 후보). 보조그리드(베스트셀러/순위추적/경매/가격비교/상품검색)=라우터 미등록=이미 안 보임(죽은코드).
- ag-grid 3곳(Keyword/Recommend/RecommendProducts), 나머지 HTML table.
- **정리 방향(존 모델 결합)**: 키워드 3화면→**존 라벨 1화면**(황금존 등+신규/상승+시계열 토글)으로 수렴, RD=그 화면 유지. 상품시트 1개 유지+입력경로 일관화. 검수→상품시트 흡수/제거. 결과: 키워드 3곳→1곳.
- 큰 프론트 작업이라 방향 확정 후 단계적. **사장님 확정 대기**.

## ✅ 블랙리스트(제품/키워드) 완전 제거 (6/4, 커밋 952fc81)
사장님 "블랙리스트도 없애" → 전부 제거 선택. **카테고리 블랙리스트(category_blacklist/auto_filter_category_blacklist)는 트렌드 수집 필터로 별개 → 유지.**
- 프론트: 사이드바 메뉴+/blacklist 라우트+BlacklistPage 삭제 / 상품시트추가 자동차단(keywordToSheet·ShopBenchmark) / SheetRowDetailPanel ⛔버튼+onBlacklist prop / RecommendProductsPage onBlacklist 핸들러(거부버튼 Ban은 유지) / KeywordPage 차단라인.
- 백엔드: api/blacklist.py 삭제+main.py 라우터/임포트 / automation send-to-sheet is_blacklisted 제거.
- **DB 'blacklist' UserData 키 데이터는 보존**(삭제 안 함). ⚠️ 이제 예전 걸러둔 정크가 시트에 다시 들어올 수 있음.

## ✅ RD 화면 정리 (6/4) — 사이드바·컬럼·체크박스·날짜
- **키워드 추출(RD) 사이드바 최상단 이동**(더보기→메인 1번, 커밋 f20ddce).
- **컬럼 순서 원본 동일**: .xlsm `listKeyword`(table4, v1.4.3) 27열 순서 추출→KeywordPage colDef 재배치(조회날짜·카테고리·분류·순위·키JP·키KR·경쟁강도·검색주평/전날·전체상품수·일/한/중/그외·낙찰수·낙찰시가·9~2위·낙찰종가·전날대비증감). **연관키워드수**(원본6열)=메인 키워드 데이터 없어 미추가(껍데기방지). **volume_change_flag(전날대비증감)** 신규노출. 존/구좌/한국비율 보조는 뒤에(드래그 이동). colState 키 v2 bump.
- **체크박스 2개 중복 수정**(커밋 a39ed6f): ag-grid v35 rowSelection 신API가 체크박스 자동생성인데 수동 colDef에도 있어 중복 → 수동 삭제, selectionColumnDef(pinned left, selectAll:filtered)로 일원화.
- **날짜 UI 캘린더화**(a39ed6f): 캘린더 상시노출 + ◀▶ 하루씩(데이터 있는 수집일만) + '최신' + 건수표시. 전체/기간은 보조. 기본=최신 수집일 1일(기존 유지).

## ✅ 연관검색어 경쟁강도/낙찰가 검증 실배선 (6/4, 커밋 21a06e2)
사장님 "연관검색어 경쟁강도/낙찰가 체크하려면?" → 조사결과 **껍데기**였음: `related.py` run_competition/run_bid 정의만 있고 미사용 + UI 체크박스 disabled('미구현'). **프론트는 이미 페이로드 전송 중** → 백엔드 연결+체크박스 활성화로 완결.
- **run_competition**: 수집 연관어 → M03 CompetitionScraper(큐텐 검색) → total_products/products_jp·kr·cn·other/competition_intensity 머지 후 save_keywords. → 존 분류 작동(상품수 축).
- **run_bid**: M04 BidResultScraper → replace_bid_history(BidHistory 적재, RD 그리드 keyword_jp 조인 표시). 느림(키워드당 QSM 경매조회).
- RelatedBulkPage 체크박스 disabled 해제+'미구현' 라벨 제거. 기존 e2e검증된 M03/M04 재사용.
- ⚠️ **구조적 한계**: **검색수(주평)는 임의 연관어에 못 채움** — search_volume_weekly는 M02 ADPlus 트렌드 수집기 전용(특정 키워드를 트렌드 테이블에 넣어야 나옴). M03은 검색하면 뜨는 상품수(공급)만 측정. 그래서 연관어 "경쟁강도(=상품수/검색수)"는 검색수 없어 0/None, **상품수만 채워짐**→존의 상품수 축만 작동. 원본 VBA도 동일 구조.
- ✅ **풀 e2e 검증 완료(6/4)**: 백엔드 재시작(새 코드 로드, PID 22744)+자동 쿠키 재로그인 복원 → `/related/collect` (seed=アヌア, google_suggest만, run_competition=true, run_bid=false) → "연관 9개 적재 완료" + M03 9/9. **DB 실확인: 연관어(분류=구글자동) 9건에 상품수 채워짐**(アヌア美容液=6647, pdrn=3288, 化粧水=3302…), **검색수=전부 null → 경쟁강도 null**(임의 연관어 검색수 불가 한계 실증). 트렌드(3.주간)는 검색수·경쟁강도 다 있음(대조 확인).
- ✅ **국가별 0 → 원본 VBA 방식으로 복원 완료(6/4, 커밋 8d24e39)**: 원인=M03 `_get_country_products`가 `[data-nation_code]`(=.local, 국가명만 inner_text)를 읽어 숫자 없어 0. 원본(keyword_vba L3706~) 그대로 `#div_global_domestic_tab > .tab` 각각 `.local[data-nation_code]`+형제 `.num('(1,234)')`로 수정. **e2e: 化粧水 → JP56,919/KR71,546/기타3,551(예전 전부 0→정상). CN=0은 큐텐 CN탭 폐지(기타 병합), 원본도 동일.**

## ✅ 실시간 환율 → 마진계산 연결 (6/4, 커밋 c581703) — "스모킹건" 해소
사장님 "환율 마진 연결 진행". 진단: get_exchange_rate(Dunamu) 있으나 마진 9.5 하드코딩+프론트 미호출. **실측상 Dunamu 호스트가 백엔드서 unreachable(rate:0)**이었음(번역 httpx는 정상=Dunamu 특정 문제).
- **백엔드**: exchange_rate.py 재작성 — **1엔당 원화로 통일**(basePrice/currencyUnit), **하루1회 캐시**, Dunamu 실패→**open.er-api.com 폴백**→직전캐시. get_exchange_rate_meta(출처/날짜). `/utils/exchange-rate`가 rate+source+as_of 반환. ⚠️단위주의: 마진은 1엔당(~9.5), price_compare는 `>20이면 /100` 가드라 단위 안전(둘 다 호환).
- **프론트**: `lib/exchangeRate.ts` 공용(fetch+localStorage 날짜캐시, getCachedRate 동기, 모듈로드 워밍). MarginPage 기본 환율=오늘 라이브+'오늘 N원·출처(날짜)' 표시+적용버튼. productSheet newSheetRow 환율=getCachedRate()→새 시트/추천행 자동주입.
- **e2e 검증**: `/utils/exchange-rate` → **9.5616 (er-api, 2026-06-04)**. Dunamu는 죽어서 폴백이 살림. (기존 하드 9.5와 근접 = 옛 추정 우연히 양호했음.)
- ⚠️ 잔여 `?? 9.5` 폴백 다수(RecommendProductsPage 6곳·ReviewPage 등)는 안전망으로 유지(새 행은 이미 라이브 주입). 필요시 getCachedRate()로 교체 가능. ReviewPage는 비활성 흐름이라 후순위.
- ⚠️ 백엔드는 `--reload` 없이 구동(`python -m uvicorn app.main:app`) — 코드 수정 반영하려면 재시작 필요. 강제종료 시 Playwright Chrome 고아 가능성 있으나, 재시작+`/api/auth/verify`로 브라우저 강제 기동+쿠키 검증하면 복원됨.

## 🖥️ 맥북 24h RD 자동화 셋업 — 진행중 (6/5)
RD 스택이 GPU·AI·유료API 없이 브라우저+httpx만 쓰게 돼서(번역=Papago웹, 환율=er-api) Intel 맥북 구동 가능 확정. 셋업 자료 일체 작성·푸시(커밋 93e724d·49a7e2b·ac04230). 깃 원격=`github.com/handsombros-arch/qoo10-keyword-extractor`.
- **셋업 자산**: `automation/mac/README_맥북셋업.md`(초보용 단계 가이드) + `setup.sh`(venv+`requirements-mac.txt` 설치+launchd plist 생성) + `com.elviten.backend.plist.tmpl`(백엔드 KeepAlive LaunchAgent) + `com.elviten.rd-daily.plist.tmpl`(매일4시 trigger_daily_rd.py). `.gitattributes`로 .sh/plist LF 강제(CRLF 실행오류 방지).
- **`backend/requirements-mac.txt`(신규)**: torch/sentence-transformers/ollama/google-generativeai 제외(이미지매칭·LLM용, RD 불필요 + 전부 lazy import라 빼도 백엔드 기동 OK). ⚠️**torch는 Intel 맥에 wheel 자체가 없음**(파이썬 버전 무관). 컴파일/Rust 회피 위해 pydantic>=2.10·asyncpg>=0.30·sqlalchemy>=2.0.36·playwright>=1.49 로 완화 → py3.14 휠로 설치 성공.
- **browser/manager.py**: Chrome 경로에 macOS/Linux 추가(커밋 57ef2c5).
- **맥북 실측(6/5, 사장님이 맥에서 직접 진행)**: macOS 12(Monterey)/Intel/**Python 3.14.5**. ✅git clone(레포 임시 Public 전환 — 구글OAuth 계정이라 PAT/비번 없음→Public이 제일 쉬움) ✅setup.sh로 슬림 설치 완료 ✅`backend/.env`에 DATABASE_URL 1줄 넣음(이걸로 충분).
- **🔴 막힌 지점**: 백엔드 LaunchAgent 로드가 `launchctl load`·`launchctl bootstrap gui/$(id -u)` 둘 다 **"Input/output error(5)"** 로 실패. plist 점검(plutil -lint/cat/python경로) 단계에서 중단.
- **다음(맥 Claude Code로 이어감)**: ①launchd I/O에러 진단(안 되면 우선 `backend/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` foreground로 동작검증) ②Chrome 뜨면 QSM 로그인 1회(사장님) ③`trigger_daily_rd.py --cats 3,7` 수집테스트 ④rd-daily.plist 매일스케줄 ⑤맥북 잠자기 끄기(`pmset -a sleep 0`). 사장님이 **맥에서 Claude Code 열어 직접 실행**하기로(원격 복붙 대신) — 핸드오프 프롬프트 전달함.
- ⚠️ **README/setup.sh가 `launchctl load`를 안내** → 실패 확인됨. **`launchctl bootstrap gui/$(id -u)`로 가이드 수정 필요**(그것도 I/O에러면 plist 원인 별도). 후속 반영 TODO.

## 순위추적(M10) 상태 (6/4 확인)
사장님 "원본 순위추적 구현되나?" → **코드는 다 있으나 현재 작동 안 함**:
- 백엔드 `m10_ranking_tracker.RankingTrackerScraper`(qoo10.jp/s/{kw} 검색→상품ID로 순위 탐색) + `/api/tracking`(items/history/run, main.py:160 등록) + tracking_items/history DB = ✅ 살아있음.
- 프론트 `TrackingPage.tsx` = ⚠️ App.tsx 라우터 미등록(orphan, 화면 접근 불가).
- **M10 셀렉터 전부 노후**(6/4 실측): `.s_item_group .s_item`/`.goods_list li`/`[data-item-no]`/`a[href*='/g/']` 모두 0개. 현 큐텐은 `[class*='item'] li`(583) 구조. → 순위 못 찾음(전부 미발견). 원본에도 M10 있으나 동일하게 노후됐을 것.
- **살리려면**: ①M10 셀렉터 현행화 ②TrackingPage 라우트+사이드바.
- ✅ **①완료+e2e 검증(6/4, 커밋 직후)**: M10 `_find_product_rank` goodscode 방식 재작성(`[goodscode]` DOM순서 중복제거→순위, URL `?keyword=`). 구 셀렉터(.s_item_group/.goods_list/[data-item-no]/a[href*=/g/]) 전부 폐기됨 확인. **e2e 테스트: VT시카크림(goodscode 1033634836) シカクリーム 추적등록→/api/tracking/run→rank 8위 정확히 잡혀 tracking_history 저장. task completed.** 실제 작동 확인.
- ⚠️ **남은 것=②UI 노출만 — 사장님 "나중에"(6/4) 보류**: TrackingPage orphan 그대로. 나중에 App.tsx 라우트+사이드바 추가하면 사용 가능. 테스트 항목 "VT 시카크림(테스트)"(tracking_items id=1) DB에 남겨둠(UI 살릴 때 정리).
- 참고: `/api/tracking/run`이 task_id 미반환(폴링 불편, 경미) — 결과는 history로 확인.

## ✅ 낙찰가 수집 기본 ON (6/4, 커밋 0fc264d)
사장님 "데이터 불러올 때 낙찰가도 같이 가져와야 함." → `collect_bids` 기본 false→true (`schemas/keyword.py:37` + `KeywordPage` collectBids useState). 그동안 기본 OFF라 **5/13 이후 BidHistory 전무**했음(그 전엔 collect_bids 켰을 때만 수집). 이제 키워드 수집 시 M04 경매낙찰가 같이 수집→BidHistory 저장→낙찰 컬럼 채워짐.
- ⚠️ **느림**: M04는 키워드마다 QSM 경매페이지 조회(670개=수십분). 원래 OFF였던 이유. 체크해제로 끌 수 있음.
- M04는 5/13까지 작동(QSM 셀러페이지=비교적 안정). 활성화=백엔드 재시작+프론트 하드새로고침.
- ✅ **M04 e2e 검증(6/4)**: `/api/bid/collect`로 カラコン/アヌア/リップ 수집 → task completed, 실제 낙찰가 순위별 유입(カラコン 낙찰수16 종가495,100엔 / アヌア 5,100 / リップ 140,900). **M04 셀렉터 멀쩡(노후 아님)** — 낙찰가 안 들어온 건 오직 collect_bids OFF 때문이었음. 이제 기본 ON이라 수집 시 같이 들어옴. (bid/collect는 BidHistory만 갱신=키워드 데이터 불간섭, 안전.)

## KeywordPage 데이터 품질 (6/4 조사)
- **경쟁강도 정렬 "안 먹힘" 원인**: `getKeywords()`가 날짜파라미터 없이 `/keywords` 호출 → **전 날짜 8,900행(17일치) 통째 로드**. 같은 키워드 날짜마다 중복 → 정렬이 무의미해 보임. + 경쟁강도 NULL 775개(연관/자동완성=M03 미측정). 타입은 정상(float). **고칠 점=한 날짜만 로드/필터.** 사장님: "원본 기준"(원본은 시트 한 장=한 날짜만 봄) → 날짜 스코핑이 맞음.
- **정렬 수정(6/4, 커밋 8411aa6)**: 정렬 기능 자체는 정상(sortable+numericColumn+float, onSortChanged/onGridReady 핸들러도 정렬 리셋 안 함). 원인=전 날짜 무차별 로드. **fetchDates에서 기본 dateMode='single'+최신날짜로 초기화** → 단일날짜(~670행) 뷰로 정렬 정상화. 프론트 dist 재빌드함(하드새로고침 필요). 브라우저 클릭 검증은 사장님 몫.
- **"0,1,2,45899"**=경매 낙찰 컬럼(낙찰수 0,1,2.. / 낙찰가 엔). BidHistory(M04) 조인. 광고입찰 없는 키워드(7800/8900)는 None→빈칸. 정상 데이터지만 희소.
- **중국(products_cn) 항상 0 = 큐텐이 CN 탭 폐지(その他/OT에 병합)** 때문. 현재 큐텐 국가탭=전체/JP국내/KR한국/OT기타(CN 없음). **원본 VBA도 동일 로직(CN 분기 + `If strCN="" Then 0`)이라 원본도 지금 0**. 엘비텐 코드 정상=원본과 동일. **사장님 결정: 원본 기준 = 중국 컬럼 그대로 유지(CN 탭 되살아나면 자동 채움). 변경 없음.** keyword_jp 깨진 데이터는 DB에 0개(curl 파이프 표시 artifact였음).

## ✅ 키워드 발굴 엔진 — 최종 확정 (6/3)
**목적(사장님)**: 내 키워드·연관키워드를 넘어 **"찐 일본 유저가 실제로 검색하는 말"**을 찾아 상품명·태그 SEO에 사용.
**핵심 구조**: 소스는 "후보 어휘"만 생성, **검증은 전부 큐텐 M03(검색수+경쟁강도)로 통일** → 존 분류. (구글 등 검색량 못 얻는 한계를 큐텐 자체 데이터로 해결 — 사장님 지적).
```
[발굴] 자동완성+검색엔진+커뮤니티 → [큐텐 M03 검증: 검색수+경쟁강도] → [존 분류] → [상품명/태그 SEO]
```
**최종 소스 세트 (3계층):**
- **L1 구매검색 자동완성**: 큐텐(광고연관/자동완성/연관)✅유지 + 야후쇼핑(자동완성/연관)✅유지 + 아마존JP(자동완성/연관)🔨구현.
- **L1b 검색엔진 자동완성**: 야후웹(자동완성/연관)🔨구현 + **Google サジェスト🔨신규(확정, "찐 검색어" 최고 소스, 원본에도 없던 업그레이드)**.
- **L2 커뮤니티·블로그 자연어(태그 기반)**: @cosme🔨 + LIPS🔨 + 아메블로(blogtag)🔨. → "상품명/태그용 자연어 어휘". 본문 형태소분석은 2차(나중).
- **제거**: 라쿠텐·Rakko·KeywordTool (원본도 빈 껍데기).
- **연쇄(원본 opWithAnalysis/opWithResultBid 차용)**: 존 목록에서 키워드 선택 → [연관키워드 추출(+☑경쟁강도 ☑경매낙찰가 ☑검색수0제외)] / [경쟁강도 분석] / [경매낙찰가 분석]. 추출된 연관키워드도 자동 M03→존 분류(발굴 꼬리물기). 직접 JP/KR 입력창도 보조 유지.
- **고아 페이지 거취 갱신**: `/competition`(M03)·`/bid`(M04) = **삭제 말고 존 화면 액션으로 흡수**(재활용). 나머지 고아(/products·/price-compare·/tracking·/bestsellers) 거취 미정.
- **실현성**: Google/Yahoo サジェスト·知恵袋·@cosme/LIPS/아메블로 = 무료 스크래핑 가능(크롬확장 경유, 속도제한). 무료 검색량 API는 불가 → 큐텐 검색수로 대체.
- **봇차단**: 아마존 강(확장 필수), 나머지 약~중.

## ✅ 발굴 엔진 읽기전용 테스트 (6/3) — 기존 소스 실작동 검증
임시 격리 브라우저(앱 프로필 안 건드림, DB 저장 X)로 공개 소스 3종 실행:
- ✅ **야후쇼핑 자동완성**: 작동. `韓国コスメ ほうれい線クリーム/50代/シミ取り効果` 등 실키워드 8개.
- ✅ **큐텐 자동완성**: **셀렉터 노후로 0개였음 → 수정 완료(커밋 0fe3c9d)**. `#auto_keyword`→`[class*='auto'] li a`. 수정 후 31개(`韓国コスメ ダルバ`, `シカクリーム vt/ドクタージャルト/ネイチャーリパブリック` 등 브랜드+속성 실키워드). autocomplete.py.
- 🔧 **야후쇼핑 연관**: URL 리다이렉트(`search.shopping`→`shopping.yahoo.co.jp/search/.../0/`)+DOM 변경 → 0개, **재작업 필요**(우선순위 낮음, 자동완성이 이미 양질).
- **교훈**: "구현됨" ≠ "작동함". 스크래퍼는 셀렉터 노후 상시 점검 필요. autocomplete 소스가 "찐 일본 검색어(브랜드+속성)" 목적에 정확히 부합 확인.
- **야후웹(쇼핑 아님) 테스트(6/3)**: 관련검색(関連検索ワード) ✅ 됨(`韓国コスメ 人気 50代`, `シカクリーム 効果/vt/シミ` 등, 단 셀렉터 넓어 사이트명 노이즈 섞임→`関連検索ワード` 섹션으로 좁혀야). 야후웹 자동완성 ❌ 0개(top page 검색창 미작동, 추가작업). → 야후웹은 "관련검색" 중심으로 구현 가치(일반 검색의도+질문형 `○○とは` 포착).

## 🔑 연관검색어 저장 경로 = "중복 시트" 문제의 뿌리 (6/3 확인)
- 모든 연관/자동완성 소스 결과 → `related.py:158 save_keywords()` → **트렌드와 같은 `keywords` 테이블**. classification(자동완성/연관/유사/야후쇼핑자동/야후쇼핑연관)+source로 구분. lookup_date=오늘, **category 없음**.
- save_keywords delete는 (date AND category AND classification) 다 있을 때만 → category 없는 연관어는 **delete 안 걸리고 append**(트렌드 덮어쓰기 안전). **단 기존 DB와 dedup 안 해 매 실행마다 중복 누적 가능**.
- → 트렌드+연관 모두 한 `keywords` 테이블에 쌓이고, **여러 엑셀형 화면이 제각각 또 표시** = 사장님 "중복 시트"의 구조적 원인. **존 모델로 단일 라벨 목록 통합**이 해법.

## ✅ 야후웹 자동완성 구현 (6/3, 커밋 1b2441c)
원본 분석: 우리가 안 된 이유 = 톱페이지(yahoo.co.jp)에서 타이핑(0개). **원본 방식 = `search.yahoo.co.jp/search?p={kw}` 진입 → `.SearchBox__searchInputWrap` 클릭 → `#assist li`**. 현 DOM에서 검증됨(`アヌア 美容液/口コミ/レチノール/pdrn` 등 클린).
- `autocomplete.py: yahoo_autocomplete()` 신규(노이즈 필터: 設定/Agent/聞いて/검색이력/`~へ`광고). make_keyword_dict 에 "야후자동" 추가.
- `related.py` 요청필드(yahoo_autocomplete)·디스패치·page조건·총스텝·검색수0필터 배선.
- `RelatedBulkPage` 토글 enabled:true + **payload에 yahoo_autocomplete 전송 추가**(기존엔 토글 켜도 백엔드로 안 보내던 껍데기였음).
- 검증범위: 스크래퍼 함수 직접 실행(클린 추출) + 백엔드 py_compile + 프론트 빌드 통과. **풀 e2e(UI→DB)는 QSM 로그인+서버 기동 필요 — 미실행.**
- **남은 신규 소스**: 아마존JP(봇차단 강), Google サジェスト, @cosme/LIPS/아메블로(태그), 야후쇼핑 연관 셀렉터 재작업.

## ✅ 원본 방식 연관소스 일괄 포팅 (6/3, 커밋 f5e683f) — "원본 되면 우리도 된다" 전제로 진행
원본 VBA selector 현재 DOM 진단 결과 **전부 작동**(아마존 봇차단도 없음, headless OK). 원본 방식 그대로 포팅+검증:
- **amazon_autocomplete** ✅: `amazon.co.jp/s?k=` → `#twotabsearchtextbox` 클릭 → `#nav-flyout-searchAjax .s-suggestion-container`.
- **amazon_related** ✅: `[data-component-type='s-related-searches'] a` / `[class*='related'] a`.
- **yahoo_related(웹)** ✅: `search.yahoo.co.jp/search?p=` + `.Contents__innerGroupFooter li`.
- **yahoo_shopping_related 수정** ✅: `shopping.yahoo.co.jp/search?p=` + `#rel_mid1 li` (기존 0개→복구).
- `_collect_items` 공통 헬퍼(UI/광고/질문형`？`/`へ` 노이즈 필터). make_keyword_dict +아마존자동/아마존연관/야후연관. related.py 풀 배선 + RelatedBulkPage 토글·payload.
- 검증: 함수 직접 실행(`アヌア pdrn/アゼライン酸`, 경쟁브랜드 `ナンバーズイン` 추출) + py_compile + 빌드. **UI→DB 풀 e2e 미실행**(QSM 로그인+서버 필요).
- **현 작동 소스(원본 구현분 전부)**: 큐텐 광고연관/자동완성/연관 · 아마존 자동완성/연관 · 야후웹 자동완성/연관 · 야후쇼핑 자동완성/연관 = **9종**. (원본 빈껍데기 라쿠텐/Rakko/KeywordTool 제외)
- **남음**: Google サジェスト, @cosme/LIPS/아메블로(태그) = 원본에 없던 신규(사장님 요청).

## ✅ Google サジェスト 추가(6/3, 커밋 88515d8) + 커뮤니티 소스 보류(결정 B)
- **google_suggest**: `suggestqueries.google.com/complete/search?client=firefox&hl=ja` JSON, 브라우저 불필요(httpx). 소비자 리서치 의도(とは/使い方/おすすめ/現地でしか/オリーブヤング) 포착. related.py page불필요 별도배치 + 토글. 검증완료.
- **현 작동 키워드 소스 = 10종**: 큐텐 광고연관/자동완성/연관 · 아마존 자동완성/연관 · 야후웹 자동완성/연관 · 야후쇼핑 자동완성/연관 · **Google サジェスト**.
- **커뮤니티 태그(@cosme/LIPS/아메블로) = 보류(결정 B, 6/3)**: 진단상 아메블로(관련 해시태그 韓国スキンケア/メガ割, UI노이즈)·LIPS(속성태그 しっとり/冷感+브랜드 rom&nd)는 됨, @cosme는 검색 URL 미발견(404). 그러나 "찐 검색어"가 아닌 "태그/자연어"라 품질·노이즈상 보조적 → Google+자동완성으로 충분 판단. 나중에 제목/태그 SEO 어휘 필요 시 추가.
- **다음 예정**: 중복 시트 정리. (단 사장님이 그 전에 별도 업무 하나 끼움 — 6/3)

## 🆕 끼운 업무 — 한국 트렌드 크롤링 (올리브영/다이소) (6/4)
**목적(사장님)**: 큐텐 데이터만 보면 반 발짝 늦음 → 올리브영·다이소 한국 라이징 트렌드를 동시에 봐야 함. 올영/다이소는 큐텐 니즈와 동행하는 경향. 큐텐 키워드와 "동일하게" 날짜별 누적 저장.
- **요구**: 전 카테고리 랭킹 **상위 30위** 데일리 크롤링 (브랜드명·상품명·가격).
- **올리브영 크롤링 가능성 ✅ 검증(6/4)**: httpx는 **403(AKAMAI)**. **Playwright headful(실 Chrome)은 통과**(메인 main.do 먼저 방문해 AKAMAI 쿠키 → getBestList.do?dispCatNo=&rowsPerPage=N). 셀렉터 `.tx_brand`/`.tx_name`/`.tx_cur .tx_num` 로 브랜드/상품명/가격 깨끗 추출(메디힐·달바 등). `ul.cate_prd_list li` 100개까지.
- **카테고리 자동추출 ✅**: 랭킹 페이지 `[data-ref-dispcatno]` 에서 122개(이름+코드) 추출됨 → **URL 수동 제공 불필요**. 상위 메인 ~13개(스킨케어/마스크팩/클렌징/선케어/메이크업/뷰티소품/더모/헤어/바디/향수/맨즈/건강·푸드) vs 하위 122개 — **범위 A(메인13)/B(전체122) 확인 대기**.
- **설계(예정)**: 스크래퍼 `kr_trend_oliveyoung.py`(메인1회→카테고리별 getBestList→상위30 파싱) + DB `kr_trend_rankings`(source/category/rank/brand/product_name/price/lookup_date, **날짜별 누적·과거 삭제 금지** — 올영도 과거 랭킹 복구 불가, [[feedback_always_commit]] 데이터보존 원칙 동일). 수동 트리거 먼저→야간 편입. 다이소는 올영 검증 후 동일 패턴.
- ⚠️ 구현 시 랭킹 탭 dispCatNo 체계 재검증(일반 카테고리트리 10000... vs 랭킹 900000... 코드 상이 가능).

### ✅ 올리브영 크롤러 구현 완료 (6/4, 커밋 64f432d)
- **메커니즘 확정**: `getBestList.do?dispCatNo=900000100100001`(판매랭킹 고정) + **`fltDispCatNo={카테고리 트리코드}`** + `rowsPerPage=30`. (트리코드 10000010001 직접 dispCatNo는 0개 → fltDispCatNo로 필터하는 구조). 메인 main.do 먼저 방문해 AKAMAI 쿠키 확보 필수.
- **카테고리**: 사장님 결정 A = 메인 20개(스킨케어/마스크팩/클렌징/선케어/메이크업/뷰티소품/더모/네일/헤어/바디/향수/맨즈/건강식품/푸드/헬스/구강/위생/패션/홈리빙/취미) × 30위. 코드는 스크래퍼에 하드코딩(CATEGORIES).
- **파일**: `backend/app/scrapers/kr_trend_oliveyoung.py`(crawl_oliveyoung_rankings) + `app/api/kr_trend.py`(POST /api/kr-trend/collect, GET /api/kr-trend/{date}) + `app/db/models.py` KrTrendRanking + main.py 등록 + `automation/trigger_kr_trend.py`(백엔드 API 호출형, 백엔드 실행 중 필요).
- **셀렉터**: `ul.cate_prd_list > li` → `.tx_brand`/`.tx_name`/`.tx_cur .tx_num`. _to_int로 가격 콤마 제거.
- **데이터 보존**: 저장 시 (source=oliveyoung, lookup_date=오늘)만 삭제 후 적재(과거날짜 불간섭) + **rows 비면 저장 스킵**(0건 수집 시 오늘 데이터도 보존).
- **e2e 검증**: 600행(20×30) Supabase 저장 확인(메디힐/아누아/달바/넘버즈인). 6/4 오늘 데이터 캡처됨.
- **남음**: 다이소(동일 패턴 후속) / 조회 UI(현재 API만, 화면 없음) / 데일리 자동실행(현재 수동 트리거, 야간 자동화 부활 시 편입).
- ⚠️ Windows 종료 시 asyncpg SSL teardown 노이즈(작업엔 무해, 알려진 이슈).

## ✅ 번역 Google → Papago 전환 (6/4, 커밋 c2564c7)
- **발견**: `translation.py:translate_papago = translate_google` — 코드에 "papago"라 써있어도 **전부 Google 무료 endpoint**였음(원작자가 papago 비공식 웹 어려워 폴백). 상품명 jp→ko 의미번역만 ollama LLM(별개, 캐시 있음).
- **사장님 결정(6/4)**: 품질 위해 Papago로 전환(c). ⚠️ 옛 무료 Papago(developers.naver.com 일1만자)는 2024 종료 → **현 Papago = NCP 종량 유료**. 사장님 "API X"는 비싼 LLM 기준이고, **번역은 ₩20/1천자 + 캐시로 푼돈**이라 별개로 수용.
- **구현**: `_papago_api`(NCP NMT, X-NCP-APIGW 헤더) 우선 → 실패/크리덴셜無면 `translate_google` 폴백. `translate_text`=캐시(TranslationCache)→Papago→Google→캐시. `translate_batch`/`translate_papago` 모두 이 경로. **크리덴셜 없어도 Google로 안 깨짐**(검증: 韓国コスメ→한국 화장품, 캐시 hit).
- **활성화 대기**: 사장님이 **NCP(네이버 클라우드)** 콘솔서 Papago Translation Application 등록 → Client ID/Secret 발급 → `backend/.env` 에 `PAPAGO_CLIENT_ID`/`PAPAGO_CLIENT_SECRET` 추가 → 백엔드 재시작. 입력 전까진 Google+캐시로 동작.
- **NCP 공식 문서 확정(6/4, 커밋 dbba418)**: endpoint=`POST https://papago.apigw.ntruss.com/nmt/v1/translation`(구 naveropenapi 아님, 현행으로 수정함). 헤더 `X-NCP-APIGW-API-KEY-ID`/`X-NCP-APIGW-API-KEY`, 파라미터 source/target/text(최대5000자), 응답 `message.result.translatedText` — 모두 구현과 일치. **`developers.naver.com` Papago(구 오픈API)는 2024-03-01 종료, 문서만 잔존(사장님이 본 detectlangs 링크가 그것) — 사용 불가**. 살아있는 건 NCP뿐.
- **부수효과**: 키워드 번역 경로에 **캐시 신설**(기존 Google 경로는 uncached였음) — [[project_qoo10_no_api_roadmap]] "번역 캐시화" 일부 달성.
## 🆕 끼운 업무 — 네이버 쇼핑 수집 "왜 원본은 되는데 우린 안 되나" 분석 (6/4)
사장님: 원본은 네이버 쇼핑 수집이 잘 되는데 엘비텐은 우회+확장 깔고도 잘 안 됨 — 차이 분석.
**진단(코드/VBA/브라우저로 검증 완료):**
- ① 엘비텐 검색=네이버 **Open API**(`m08_naver.py`, `openapi.naver.com/v1/search/shop.json`, X-Naver-Client-Id, 무료 25k/일). `lprice`만 주고 **배송비·옵션 없음**(코드주석 "카탈로그 옵션/배송 dead-end"). ✅
- ② 옵션/배송은 상세페이지 필요 → **확장 naver-smartstore.js**가 smartstore SPA `__PRELOADED_STATE__`의 `productDelivery`/`optionCombinations` **sub-store**를 노림. 근데 client-side 늦게 로드 → 폴링 놓침 → **6/8 필드, 옵션/배송 실패**(polled_attempts 디버그필드 도배가 증거). ✅
- ③ 원본은 **SeleniumBasic이 진짜 분리 Chrome 구동** → `search.shopping.naver.com/search/all` **검색결과 DOM**에서 가격+샵+**배송비**(`deliveryInfo_info_delivery`)를 리스트레벨에서 한 번에. 어려운 상세SPA 안 건드림. ✅
- ⭐ **추가 확정(6/4 브라우저 테스트)**: **Playwright 헤드풀(진짜 Chrome 실행파일)로도 네이버 검색결과는 AKAMAI 차단**(로그인 리다이렉트, 상품0). 올영은 Playwright 통과하나 네이버는 막음. → 네이버 접근=API(배송無) 또는 진짜 메인Chrome(확장)뿐. **Playwright 중간경로 불가**. 이게 엘비텐이 API+확장 쓴 이유.
**근본원인**: 엘비텐이 검색을 깔끔한 API로 갈아타며 "리스트 레벨 배송비"를 잃고, 가장 어려운 상세SPA(옵션/배송 sub-store)로 스스로 내몰림. 원본은 진짜Chrome으로 검색리스트에서 다 끝냄.
**해법방향**: 확장(진짜 Chrome)으로 **검색결과 페이지**를 열어 원본처럼 리스트에서 배송비 추출(상세SPA 회피). B 반자동 루프는 옵션 자동수집 비활성 방향이라 배송비만 해결하면 충분.
⚠️ **미검증**: 현재 네이버 검색결과 페이지에 배송비가 여전히 있는지 — Playwright로 못 열어 확인불가. **사장님이 평소 Chrome으로 `search.shopping.naver.com/search/all?query=X` 열어 상품별 배송비 표기 확인 요청함**(6/4). 있으면 확장에 검색결과 배송비 추출 구현.

### ✅ 프로브 1단계 완료 + 구조 확정 (6/4, 커밋 1e3026b)
- 확장에 `naverSearchDump`(background.js) + `POST /api/ext/naver-search-probe` + result 파일저장(extension.py) 추가. 백엔드 재시작(PowerShell로 직접) + 확장 토글 후 프로브 실행 → `logs/naver_search_probe_20260604_144214.json`(981KB) 획득.
- **결과**: 확장(진짜 Chrome)으로 네이버 **차단 없이 통과**(login_redirect=False). 배송비 검색결과에 **있음**(`배송비 2,500원`, DOM class `price_delivery_fee__*`).
- **구조 = Next.js `__NEXT_DATA__`**(`__PRELOADED_STATE__` 아님 — 기존 우리 코드가 못 잡던 이유). 메인 organic 리스트는 SSR `__NEXT_DATA__.props.pageProps.superSavingProducts`(외 리스트들, 총 productTitle 59개)에 **배송비까지 구조화**: `productTitle`/`productName`, `lowPrice`/`price`, **`dlvryFee`/`krwDlvryFee`/`deliveryFeeContent`/`dlvryCont`(배송비)**, `mallName`, `mallProductUrl`(smartstore 직링크!), `category1~4Name`, `imageUrl`, `rank`, `maker`, `reviewCountSum`, `mallProductId`.
- **해법 확정(원본보다 우수)**: 원본은 깨지기쉬운 DOM클래스(basicList_*, "22.11.27변경" 도배) 긁음. **우리는 확장이 `__NEXT_DATA__` 떠서 구조화 데이터 파싱** → 셀렉터 안 깨짐.
- **2단계(파서) 완료**: 확장 naverSearchDump가 next_data 덤프 → 백엔드가 `props.pageProps`의 상품리스트들(superSavingProducts + 그 외) 파싱해 title/price/배송비/shop/url/category/image 추출 → 매칭/소싱 흐름 연결. 덤프파일 `logs/naver_search_probe_20260604_144214.json` 보존(파서 작성·테스트용).

### ✅ A안: 네이버 검색을 확장으로 대체 완료 (6/4, 커밋 16430f0·f686bf3·86c7cbe·41597d7)
- **메인 리스트 경로**: `next_data.props.pageProps.compositeList.list[].item`(type=product, 46개) + `superSavingProducts`(13). 배송비=`dlvryFee`(문자 '0'=무료/'2500'=원). 직링크=`mallProductUrl`(smartstore).
- **파서**: `backend/app/services/naver_search_ext.py` `parse_naver_search_dump(dump)` → product_name/price/**shipping_fee**/shop_name/product_url/category/image/rank. 덤프 검증: 50개, 무료25·유료25, 배송비 정확.
- **확장 연결**: background.js `naverSearchDump`(검색URL이면 __NEXT_DATA__+DOM샘플 덤프) + extension.py `/result`가 mode=naver_search면 파싱해 `results[url].parsed_products` 저장. ext_client `search_one(keyword)`=검색잡 enqueue→poll→products.
- **m08 대체**: `m08_naver.NaverShopScraper.run()`에 확장검색 우선 분기(`EXT_USE_EXTENSION` 기본 **true**, 상세경로와 일관) + `_build_from_ext`(의미필터+가격순+배송비 채움). **출력형식 유지**(source/product_name/price_krw/shipping_fee/...) → 호출처(keywords/recommendations/products) 무변경 자동적용. 기존 `shipping_fee=''` → 이제 실제 배송비(원, 0=무료). 확장 미가용/0건 시 네이버 API 폴백.
- **활성화**: 백엔드 재시작(새코드) + 확장 실행 필요. 지연 ~30~75s(확장 1분 alarm; popup 즉시폴링으로 단축) vs API ~1s — 온디맨드 B반자동 소싱엔 OK.
- ⚠️ **"옛 크롤러 삭제"는 보류(다 살아있는 흐름에 물림)**: `naver_session_check`=`daily_workflow.py:443`(야간 로그인점검)이 호출, `naver_fetch_v2`=콘텐츠재생성·JP상세(products.py·qoo10_jp_detail.py) 사용 중. 단독삭제 시 깨짐 → 그 흐름들 먼저 확장 이전 후에나 삭제 가능(별도 작업). naver-login-setup은 naver_fetch_v2 헬퍼 사용이라 유지.

## 번역 — Papago 웹 자동화로 전환 (6/5 완료, 커밋 c7caf87)
- **6/4**: "일단 Google로". → **6/5 원본 비교에서 구글 번역 품질 약점 실측** → Papago 웹으로 전환.
- **발견**: 원본 키워드추출기는 NCP 유료 API가 아니라 **papago.naver.com 웹을 Selenium 구동**(무료)으로 고품질 번역. (`번역_일본어to한국어` VBA L9768: `papago.naver.com/?sk=ja&tk=ko&st=` + `#txtTarget` 읽기 + 줄바꿈 배치). 별도 번역DB 없음 — 키워드(한국어) 컬럼 자체가 캐시(이미 차있으면 스킵).
- **구현**: `papago_web.py`(papago_translate_batch, #txtTarget, 줄바꿈 배치) + `browser_manager.new_page()`(QSM 메인탭 불간섭 별도탭) + `translate_batch` 재작성(캐시→Papago웹 20개청크→구글폴백→캐시). 키워드 한국어 경로(keywords.py 323/478/1041) 자동 적용. 브라우저 미가용 시 구글 자동폴백.
- **검증**: Papago 웹이 원본과 동일 — マスク→마스크(구글 가면X), 脱毛→제모(구글 탈모X 의미오류), アスタリフト→아스타리프트, シナモロール→시나모롤, パンパース→팬파스. 신규 캐시미스도 Papago(除毛→제모).
- ✅ **기존 데이터 Papago 재번역 완료(6/5)**: 전체 고유 키워드 1,239개를 papago-test로 직접 재번역(캐시 미경유)→**1,235/1,239(99.7%) 성공**(4개만 papago 멀티라인 이슈로 구글 유지). **keyword_kr 9,500+행 UPDATE**(검색수/상품수 등 불간섭, 데이터 손실 0) + TranslationCache를 papago_web으로 교체. **6/5 번역 원본 일치 51%→99.3%**(다른 3건도 동의어/음역 차이일 뿐 오역 아님: 가방vs백, 구강청결제vs마우스워시). Papago 웹 = 원본 동급 확정.
- translate_text 단건(recommendations/related)은 아직 캐시→NCP API→구글(브라우저 단건 페이지 부담 회피). 필요 시 후속.

## 6/3 추가 확정 — 연관검색어 강화 + 시트 정리 방향
- **"시트 너무 많다"의 의미**: 동일 데이터가 들어가는 **엑셀형 그리드가 여러 개(중복)**. 필요한 것만 남기고 싶음. **RD는 필수 유지.** → TODO: 어떤 그리드가 같은 데이터 중복표시하는지 매핑 후 핵심만 남기는 정리안.
- **연관검색어 원칙**: "단순 번역 ❌ → 실제 일본인이 쓰는 키워드 ✅". = **자동완성(autocomplete) 소스만** 사용(실제 검색어). brand_expand(LLM)·translate_papago(번역추론)는 step5 연관검색어에서 배제. 흐름: seed→다중소스 자동완성→dedup→각 키워드 큐텐검색해 실제 노출상품 확인→노출되는것만 채택→상품명(제목)에 사용.
- **소스 실태(related.py 실측)**: 프론트 10+개 표시되나 **백엔드 실구현 5개뿐** = 큐텐 자동완성/유사/연관(M05) + 야후쇼핑 자동완성/연관(autocomplete.py). 나머지(아마존JP·야후웹·라쿠텐·핫코·keyword_tool)는 **백엔드 없음→enabled:false 껍데기**. "왜 꺼짐"=미구현. 켜려면 스크래퍼 신규 작성 필요.
- **@cosme(코스메닷컴) 추가**: 가능+최적(K뷰티 실제 일본 키워드 1위 소스, 봇차단 약함, 크롬확장 경유). 신규 스크래퍼 필요. 자동완성/랭킹 기반.
- **소스 출처 규명(git+원본 실측)**: 엘비텐 연관소스 껍데기들은 초기커밋 8705d88(4/18)에서 **원본 frmRelatedKeywords 체크박스를 UI만 미러링**한 것(사장님 요청 아님). 원본엔 op체크박스 있으나 **일부는 원본도 빈 껍데기**.
- **원본 연관소스 실구현 판별(본문 줄수+주석)**: ✅실구현=큐텐AD연관/Auto/Related, 아마존JP Auto/Related(Selenium amazon.co.jp), 야후JP웹 Auto/Related, 야후JP쇼핑 Auto/Related. ❌원본도 빈껍데기=**라쿠텐**(주석 `'봇 감지되어 동작 못함`), **Rakko**(빈), **KeywordTool**(빈).
- **6/3 확정 빌드목록("원본에 있으면 모두 구현"+"껍데기 금지")**: 🔨신규구현=**아마존JP 자동완성/연관**(봇차단강→크롬확장 경유) + **야후재팬(웹) 자동완성/연관** + **@cosme**(사장님요청,신규). ✅유지=큐텐3·야후쇼핑2(이미 있음). 🗑️제거=라쿠텐·Rakko(핫코)·KeywordTool 빈체크박스(원본도 포기한 것, 만들면 또 껍데기).
- **대기**: 기존 5소스 실작동 검증 / 빌드 착수 시점(데이터가드·필터·시트 정리와의 순서).

## 🚫 제외 확정 (6/4) — LLM 호출 캐시/감축
사장님 "LLM 호출 [캐시/감축]은 없음". B 반자동에서 무거운 AI(이미지매칭·자동상세·자동검수) 이미 비활성 → 줄일 LLM 호출 자체가 없음. **no-API 로드맵의 'LLM 호출 캐시 3종(category/brand/image)' 과제 = 폐기.** (번역 캐시는 이미 신설됨, 별개.)

## 정리 대상 (조사 6/3 확정)
- **고아 6페이지** (코드·API 멀쩡, 라우터/메뉴서 빠짐): /competition /bid /products /price-compare /tracking /bestsellers → 삭제 or '분석' 메뉴로 부활 결정 필요.
- **M12 sales_volume 스크래퍼**: 완전 죽은 코드 → 삭제.
- **m07/m08 Playwright ↔ 크롬확장 이중 경로** + naver_fetch_v2/naver_session_check fallback → 확장 단일화.
- **no-API 캐시 미구현**: category_cache/brand_expand캐시/image_match_cache 셋 다 코드에 없음(translation_cache만 존재). 로드맵 5/22 시작 기록과 달리 거의 미실행.

## 미작동 기능
- 옵션/배송비 추출(Phase 4-2): 단품1옵션만, scrape모드 봇차단으로 사실상 disabled.
- 이미지매칭 minicpm-v:8b: 한국 화장품 점수0 빈발.
- Naver 세션: false negative + 자동갱신 없음.
- JP 상세 카피: LLM JSON 파싱 실패 사례.

## 📌 9/19 세션 시작 시 확인된 현황
- 마지막 커밋 6/12 (마진시트 비용모델·묶음배송·메가수수료·클립보드 복사 — 6/10~6/12 커밋 11건). 이후 3개월 코드 변경 없음.
- **키워드 일일수집 8/21 이후 중단** (`/api/keywords/dates` 실측). 8/3~8/14, 6/19~6/22 등 결손 구간도 있고 320/220건 부분수집일 다수 → 맥북 rd-daily 잡 불안정/정지 추정. 원인 미확인.
- 윈도우 백엔드는 8000 가동 중. 윈도우 야간 작업은 5/16부터 Disabled 그대로.

## How to apply
- "목적 재정의/정리 진행" 트리거 시: ①데이터 안전 가드 먼저 → ②목적 확정 → ③고아·죽은코드 제거 → ④캐시 신설 → ⑤맥북 서버화 순.
- 어떤 정리도 `keywords` 등 누적 테이블 DROP/DELETE 동반 금지. 마이그레이션은 ADD COLUMN만.
- [[project_qoo10_no_api_roadmap]] 후속·통합본. [[feedback_qoo10_local_ai]] 제약 유지(API X).
