# 큐텐 역직구 자동화 — 마스터 명세서

> **최종 갱신**: 2026-04-27
> **목적**: 향후 모든 작업의 기준 문서. 사장님이 다시 봤을 때 "왜 이렇게 정했지?" 추적 가능.
> **표기 규칙**: ✅ 완료 / ⏳ 코드만 — 검증 대기 / ❌ 미구현 / TBD = 사장님 결정 필요

---

## 1. 비즈니스 컨텍스트

한국→일본 큐텐 역직구. 한국 인기 상품을 일본 큐텐(Qoo10)에 등록해 판매.
- **운영 형태**: 셀러 1인 (사장님). 보조: AI 자동화 시스템.
- **규모 컨텍스트**: 4/25 1회 야간 자동화 — 큐텐 1036개 / 한국 1090개 상품 수집, 685개 set_count 추출, 425개 키워드 분류 완료.
- **두 PC**: 메인(RTX 5080) + Tailscale 노트북. 같은 Supabase 공유 (DB) / 코드는 git push 동기화.

---

## 2. 야간 자동화 목표

- 매일 19시(또는 사장님 지정 시각) 자동 실행 → 익일 아침 검토 가능한 추천 후보 시트 준비.
- 사장님 출근 후 **30분~1시간 검토 + 수동 큐텐 등록**.
- "**자동 업로드 X / 가격 자동 변경 X / 추천만**".

---

## 3. 7단계 프로세스 — 명세 vs 현재

### 3.1단계: 키워드 추출 + 스케쥴링

**명세 (사장님이 원하는 것)**
- 매일 야간 큐텐 트렌드 키워드(M02, ~670개/일) 자동 수집.
- Windows 작업 스케줄러 / cron 등으로 무인 실행. 모든 작업 완료 후 진행.

**현재 구현**
- ✅ M02 트렌드 키워드 스크래퍼 (`backend/app/scrapers/m02_trend_keywords.py`)
- ✅ `automation/daily_workflow.py` STEP 3 통합
- ❌ **자동 트리거 없음** — 수동 실행만

**갭**
- Windows 작업 스케줄러 등록 스크립트 없음.

**다음 액션**
- ★ Phase 5 — 다른 단계 안정화 후 마지막에 자동 트리거 등록.

---

### 3.2단계: 임계점 자동 필터

**명세**
- 한국비율 / 검색수 / 경쟁강도 기반 자동 필터.
- **프론트에서 임계값 조정 버튼 필요**.

**현재 구현**
- ✅ `POST /api/keywords/auto-filter` (`backend/app/api/keywords.py`)
- ✅ `.env`: `AUTO_FILTER_COMPETITION_MAX=2.0`, `AUTO_FILTER_KR_RATIO_MIN=0.3`, `AUTO_FILTER_VOLUME_MIN=40`, `AUTO_FILTER_CATEGORIES`
- ✅ 프론트 `/settings` 페이지 (`frontend/src/pages/SettingsPage.tsx`) — 카테고리 화이트리스트, 브랜드 자동 추가 임계값
- ⏳ 임계값 슬라이더 (competition/kr_ratio/volume) — UI 미확인

**갭**
- 카테고리 화이트리스트 외에 **수치 임계값(competition_max / kr_ratio_min / volume_min) 도 프론트에서 조정 가능해야 함** — 명세 요구.

**다음 액션**
- ★★ Phase 3 (시트 UI 통합 시) — `/settings` 에 3개 슬라이더 추가, UserData 키 `auto_filter_thresholds` 신규.

---

### 3.3단계: [브랜드 키워드] 큐텐 상위 5개 → 키워드 확장 → 한국 매칭 → 옵션·세트

**명세**
1. `is_brand=1` 키워드면 큐텐 상위 노출 + 리뷰 많은 상품 5개 파악.
2. 「브랜드 + 상품명」 일본어 키워드 추출 (예: `anua pdrn`).
3. 한글 번역 후 네이버/쿠팡 검색.
4. **노출 상품과 검색 키워드의 일치 여부 추론 (상품명 + 썸네일 동시)**.
5. 일치 시 최저가 상품의 URL/상품가/무게/배송비 추출.
6. 이미지 다운로드 — 상품 전면 + 내용물, `image/YYYY-MM-DD/` 폴더링, 큐텐 매칭 가능한 명명 규칙.
7. **옵션별 가격** (옵션 클릭 시 변동) → 큐텐 등록 세트 구성 판단.
8. 큐텐 단품/세트 파악, 세트 제안 (판매가 2만원 이하 시 묶음, 배송비 1회).
9. 행 확장 정상: 브랜드 1 → 상품명 N → 세트 N.
10. 배송비 파싱: 쿠팡 무료 / 네이버 무료/유료/조건부 (상세페이지).
11. 네이버 차단 회피 = API. 쿠팡 = scrapling으로 AKAMAI 우회.
12. 마케팅 포인트(3-4개) + 큐텐 fit 상품명/태그/옵션명(SEO).
13. 무게 OCR + **+200g 패키지 룰** (300g → 500g).

**현재 구현**
- ✅ M02 트렌드 → `is_brand` LLM 판별 + DB `brands` 화이트리스트 (`services/llm/brand.py`)
- ✅ M09 큐텐 상품 스크래퍼 (`backend/app/scrapers/m09_qoo10_products.py`) — 상위 N개 수집
- ✅ M07 쿠팡 / M08 네이버 (현재 API 키워드 단위, 광고 도용 후처리는 이번 작업으로 정비)
- ✅ 큐텐 상품명 jp→ko 번역 (`services/llm/translate.py`, prompt `jp_ko_translation.txt`, DB `translation_cache`) — 시운전 통과 (보고서 § 1, 7/10)
- ✅ 큐텐 cover ↔ 한국 cover 1:1 비전 매칭 (`services/llm/image_match.py`, prompt `image_matching.txt`)
- ✅ 텍스트 매칭 (`services/llm/text_match.py` ★ 2026-04-27 BLOCKER 처방으로 신규) — 토큰 자카드 + 부분문자열 보너스
- ✅ **결합 룰** (`api/recommendations.py`): `text_score ≥ TEXT_MATCH_THRESHOLD AND image_score ≥ IMAGE_MATCH_THRESHOLD` → accepted (광고 키워드 도용 자동 거부) — 시운전 검증
- ✅ DB `domestic_match_candidates` (qoo10_id, domestic_id, name_score, image_score, decision)
- ⏳ 브랜드 상위 5개에서 키워드 토큰 재추출(=1-D) — 코드 미구현 (작업 단위 정의됨)
- ⏳ 한국 cover 이미지 다운로드 (`services/domestic_image_pipeline.py`) — 4/25 1086장 처리됨, but `image_local_path` 폴더명 sanitize는 2026-04-27 보강 (`[, ], (, ), !, ;, ,, $` 등 제거)
- ❌ 옵션별 가격 (한국 상품 옵션 셀렉트 클릭 → DOM 가격 재읽기) — DB 컬럼 자체 없음
- ❌ 옵션별 원가 — (4-1 와 동일 영역)
- ⏳ 배송비 — `domestic_products.shipping_fee` 컬럼은 있고 텍스트 수집 중. 무료/유료/조건부 자동 파싱 ❌
- ❌ 누끼 + 내용물 이미지 분리 — 현재 cover 1장만
- ❌ OCR 무게 추출
- ❌ 마케팅 포인트 / 큐텐 fit 상품명·태그·옵션명 생성

**시운전 결과** (`docs/PHASE1_DRYRUN_REPORT.md` 참조)
- 번역 7/10, 이미지 매칭 3/10 (BLOCKER 발견 — 처방 적용 완료), set_count 비전 검증 6/10.

**갭 분석**
- 가장 큰 미구현: **옵션별 가격/원가 + 배송비 파싱 + 누끼/내용물 이미지 + OCR + 큐텐 fit 콘텐츠** — 모두 Phase 2~4.
- 매칭 정확도 검증 부족: 결합 룰이 광고 도용 거부는 확인. 정상 K-뷰티 (메디큐브 등) 매칭 검증 필요.

**다음 액션**
- ★★★ 정상 K-뷰티 키워드(메디큐브/아누아 등) 결합 룰 검증 — 큐텐 product_name_ko 충분히 채워진 후 시운전.
- ★★★ Phase 2: 옵션별 가격 스크래퍼 + DB 스키마 (`domestic_product_options` 1:N).
- ★★ 1-D 브랜드 키워드 확장 (상위 10개 토큰 재검색) — 명세 9번 행 확장 룰 자동화.

---

### 3.4단계: [비브랜드 키워드] 동일 흐름 (확장 단계 X)

**명세**
- 3.3 과 동일하지만 **큐텐 상위 5개 → 키워드 확장** 단계 없음. 트렌드 키워드 그대로 한국 검색 → 매칭.

**현재 구현**
- 3.3 과 같은 파이프라인을 그대로 재사용. 분기는 `is_brand` 플래그로 처리.

**갭**
- 분기 코드는 `daily_workflow.py` 에 명시적으로 없음 (현재는 모든 키워드를 동일 처리). 1-D 구현 시 분기 추가.

---

### 3.5단계: 시트 기록 + 실시간 재계산

**명세**
- 추출 상품을 시트 양식으로 프론트에 표시 + DB 적재.
- **원가 / URL / 무게별 배송비** 수기 변경 시 즉시 마진/이익/매출 재계산.

**현재 구현**
- ✅ `/api/recommend/auto-collected/` 엔드포인트 (`api/automation.py`) — UserData `last_auto_collected:{date}` 키에 JSON 저장, HTML 대시보드
- ✅ 프론트 `/recommend` (`frontend/src/pages/RecommendProductsPage.tsx`) — 추천 시트
- ⏳ 실시간 재계산 — 현재 정적 표시. 인라인 수정 + 재계산 hook 미확인

**갭**
- 옵션 단위로 행 펼치기 (Phase 2 데이터 의존)
- 인라인 수정 → 마진 재계산 로직 검증/구현

**다음 액션**
- ★★ Phase 3 — Phase 2 데이터(옵션·배송비) 들어온 후.

---

## 4. 핵심 비즈니스 룰

### 4-1. 매칭 기준 — 상품명 + 이미지 동시 (★ 2026-04-27 신규 정의)

**문제 배경**: 한국 셀러가 인기 키워드(예: 「하파크리스틴」)를 광고 미끼로 도용 — 「[IVE] 장원영 포토카드 HapaKristin 보라색」 같은 무관 상품이 검색 결과에 섞임. **이미지 매칭만으로는 거부 못 함** (minicpm-v 가 「패키지 디자인 비슷, 라인업 변종」 으로 score 0.7 부여).

**룰 (코드 적용 완료)**:
```
text_score  = name_similarity(qoo10.product_name_ko, domestic.product_name)  # text_match.py
image_score = compare_two_images_async(qoo10.cover, domestic.cover).score    # image_match.py
decision    = "accepted" if (image_ok AND
                             text_score  >= TEXT_MATCH_THRESHOLD  (env, 기본 0.3) AND
                             image_score >= IMAGE_MATCH_THRESHOLD (env, 기본 0.7))
              else "rejected"
```

**시운전 검증 (10쌍, 「하파 크리스틴」)**: accepted 0 / rejected 10 — 모든 광고 도용 케이스 자동 거부 ✅. 정상 매칭 검증은 후속.

**TBD**: 임계값 0.3 / 0.7 은 초기값. 실데이터 시운전 후 조정. 카테고리 일치 검사 추가 여부도 TBD.

---

### 4-2. 세트 제안 룰

**룰 (명세)**: 큐텐 판매가 **2만원 이하 → 한국 상품 3개 묶음 세트 제안**, 배송비 1회 (네이버 묶음배송).

**현재 구현**: ❌ 미구현. Phase 2 (옵션별 가격) 들어온 후 가능.

**TBD**:
- 묶음 개수 = 항상 3? 또는 큐텐 set_count 가 다른 값이면 그에 맞춤? — 사장님 결정.
- 「2만원 이하」 = 큐텐 판매가 환산 (¥) 또는 원화? — 사장님 결정 (잠정: 환산 환율 9.5 적용 후 KRW 기준).

---

### 4-3. 무게 룰

**룰 (명세)**: 상세페이지 OCR로 추출한 무게 + **200g 패키지 가중치**. 예) 300g → 500g 기입.

**현재 구현**: ❌ 미구현. Phase 4 (OCR).

---

### 4-4. 마진 임계값

**룰**:
- **마진율 ≥ 200% → set_count 비전 재검증** (작업 A, `api/products.py POST /qoo10/verify-set-counts`). 환상 마진(정규식 false positive) 자동 검증. — ✅ 코드 + 시운전 통과.
- **추천 빌드 시 마진율 ≥ 10% 통과** (`recommendations.py` `min_margin_rate`).
- **단가 환산 분모**: `unit_price = price_jpy / set_count` (set_count 자동 보정). — ✅ 적용.

---

### 4-5. 키워드 임계점

**룰 (현재 `.env`)**:
- `AUTO_FILTER_COMPETITION_MAX=2.0`
- `AUTO_FILTER_KR_RATIO_MIN=0.3`
- `AUTO_FILTER_VOLUME_MIN=40`
- 카테고리 화이트리스트 (UserData → env → 전체)

**우선순위**: UserData(/settings 슬라이더) > .env > 폴백.

**현재 구현**: ✅ 카테고리 화이트리스트는 프론트 조정 가능. ⏳ 3개 수치 슬라이더는 미확인.

---

## 5. 안전 장치

| 항목 | 값 / 위치 | 상태 |
|---|---|---|
| 비전 일일 한도 | `VISION_DAILY_BUDGET_USD=2.0` (`.env`) — 초과 시 `BudgetExceededError` 자동 차단 | ✅ |
| 모든 호출 로깅 | `logs/llm_calls/{date}.jsonl` — domain/model/latency_ms/ok/error | ✅ |
| 텔레그램 알림 | 비용 한도 초과 시 1일 1회 (실패 시 백엔드 막지 않음) | ✅ (배선됨) |
| LLM 실패 fallback (단계별) | category=「기타」 / brand=non-brand / set=1 / 번역=None / 매칭=skip | ✅ |
| **큐텐 자동 업로드 X** | HSCODE/관세 책임 — 사장님 수동 등록 | ✅ (정책) |
| **가격 자동 변경 X** | 추천 시트 표시만 | ✅ (정책) |
| 비밀 정보 .env 만 (.gitignore) | DATABASE_URL, GEMINI_API_KEY, NAVER_CLIENT_SECRET 등 | ✅ |

---

## 6. Phase 진행 순서

### Phase 1 — 매칭 정확도 (현재 — 시운전 후 잔여)

| 항목 | 상태 | 비고 |
|---|---|---|
| 1-A 큐텐 상품명 jp→ko 번역 | ✅ 시운전 (보고서 7/10) | 후처리 사전 50개 추가 시 8/10 가능 |
| 1-C 큐텐↔한국 cover 1:1 비전 매칭 | ✅ 시운전 | 결합 룰 적용 후 광고 도용 거부 검증 |
| **4-1 텍스트 매칭 모듈 ★ BLOCKER 처방 (신규)** | ✅ 코드+검증 | `text_match.py`, name_score 컬럼 활용 |
| **결합 룰 적용 (`recommendations.py`)** | ✅ 코드+검증 | 보고서 § 4#1 BLOCKER 본질 해결 |
| 1-B 번역 ko 로 한국 상품 재검색 | ⏳ 코드 X | translate-names 결과 활용 |
| 1-D 브랜드 키워드 상위 10개 토큰 재검색 | ⏳ 코드 X | 명세 3.3#1~3 자동화 |
| 정상 K-뷰티 결합 룰 검증 (메디큐브/아누아) | ⏳ | product_name_ko 더 채운 후 |
| 번역 후처리 사전 50개 (마키시무→맥심) | ⏳ | `data/jp_ko_brands.json` 신규 |
| 이미지 매칭 프롬프트 재작성 + 임계값 0.85 | ⏳ | 시운전 § 5 다음 액션 |

### Phase 2 — 옵션·배송비·이미지 폴더링

- 한국 상품 상위 10개 상세 진입 → 옵션별 가격 스크래핑 (Playwright)
- DB: `domestic_product_options` 1:N 테이블 신규
- 배송비 파싱 (무료/유료/조건부 — 정규식 + 키워드)
- 누끼 / 내용물 이미지 분리 (식품·화장품 한정)
- 세트 제안 로직 (4-2)

### Phase 3 — 시트 UI + 실시간 재계산

- 옵션 단위 행 펼치기
- 원가/URL/무게별 배송비 인라인 수정 + 즉시 재계산
- 임계값 슬라이더 (3.2 명세)

### Phase 4 — OCR + 큐텐 fit 콘텐츠

- 상세페이지 OCR (easyocr 또는 비전 LLM)
- 무게 추출 + 200g 룰 (4-3)
- 큐텐 상품명·태그·옵션명 (SEO) 생성
- 마케팅 포인트 3-4개 자동 생성

### Phase 5 — 통합 + 자동 트리거

- `daily_workflow.py` 에 모든 Phase 통합
- Windows 작업 스케줄러 자동 실행 (3.1)
- 텔레그램 알림 강화 (작업 완료 / 추천 후보 N개 / 에러)

---

## 7. 알려진 이슈

| 이슈 | 상세 | 출처 |
|---|---|---|
| **m07/m08 광고 키워드 도용** | naver source 정합 87% 이지만 「하파크리스틴」 같은 인기 키워드 도용 케이스 다수 | 보고서 § 2 + 진단 |
| **minicpm-v 양극화 (0.0/0.7)** | 사실상 binary 출력. 0.7 false positive 다수. 결합 룰로 완화 (text 결합) | 보고서 § 2 |
| **qwen2.5:7b 한자 ↔ 중국어 혼입** | 5% 빈도. 「梨子冰淇淋」「扺挡」「粑」 등. 14B 업그레이드 또는 후처리 사전 | 보고서 § 1 |
| **「マキシム」 → 「맥시멈」 의역** | 한국 정착 표기 「맥심」 미반영. 후처리 사전 필요 | 보고서 § 1 |
| **번역 시 브랜드명 누락** | 「コスノリ 眉毛脱色」 → 「이지브로우 톤체인지」 (코스노리 빠짐). 매칭 측 keyword_kr 토큰 합치기로 우회. 프롬프트 강화로 신규 번역에서 완화 예상. | PHASE1_POSITIVE_TEST § 5 |
| **번역 JSON 파싱 폴백 결함** | 달바: `{"ko": "..."` raw 가 ko 컬럼에 박힘. translate.py B-2 패치로 향후 None 반환. 기존 깨진 ko 는 reset + 재번역. | PHASE1_POSITIVE_TEST § 5 |
| **LLM 카테고리 분류 결함 (K-뷰티)** | 메디큐브/달바/dasique 등 명백 K-뷰티가 「기타」로 분류. 4/27 is_brand=1 인 29개 모두 「기타」. category.py 프롬프트/모델 점검 필요. | PHASE1_POSITIVE_TEST § 9 |
| **4/25 큐텐 데이터 22 키워드만** | 트렌드 추출은 670개/일이지만 m09 큐텐 상품 수집은 22 키워드만 진행. daily_workflow 단계 차이 점검 필요. | PHASE1_POSITIVE_TEST § 1 |
| **이미지 폴더명 특수문자 sanitize** | `[`, `]`, `(`, `)` 등 — 2026-04-27 보강 완료 (`_safe_folder_name`) | 이번 작업 |
| **상대경로 + cwd 미스 → FileNotFoundError** | `image_local_path` 가 `image/...` 상대경로. 백엔드 cwd 다를 때 fail. 절대경로 변환 패치로 해결 | 이번 작업 |
| **한국 상품 set_count 추출 없음** | 큐텐만 추출. 한국은 묶음 인식 X | STATUS.md |
| **이미지 폴더 cover.jpg overwrite** | 같은 product_name 여러 행이면 같은 폴더에 같은 파일명 — 현재는 `{source}_{id}.jpg` 로 분리됐지만 추가 검증 필요 | STATUS.md |
| **`google-generativeai` deprecated** | `google-genai` 마이그레이션 미루는 중. 사용 안 하면 OK | STATUS.md |
| **set_count 비전 false count** | 보울링백 케이스 (q=221/222/223): vision=2 인데 실제 1. confidence 0.95 신뢰 못 함 → 자동 채택 금지 + 검수 큐 필요 | 보고서 § 3 |
| **「5月」 같은 정규식 false positive** | text 정규식이 「5月」의 5 를 set_count 5 로 추출 (q=814 케이스). 비전 검증의 가치 입증 | 보고서 § 3 |

---

## 8. 미해결 갭 (우선순위)

| # | 우선순위 | 갭 | Phase / 출처 |
|---|---|---|---|
| 1 | ✅ 완료 | ~~정상 K-뷰티 결합 룰 검증~~ — 2026-04-27 23:30 완료 (accept 0% → 23%, 코스노리 7/7) | `PHASE1_POSITIVE_TEST.md § 10` |
| 2 | ✅ 완료 | ~~깨진 번역 케이스 reset + 재번역~~ — 2026-04-28 00:00 완료 (JSON 잔재 12→0, 일본어 잔존 271→189, accept 23→26, 코스노리 7→10) | `PHASE1_POSITIVE_TEST.md § 11` |
| 3 | ★★★ | 1-D 브랜드 키워드 확장 (큐텐 상위 10개 상품명 토큰 재검색) | Phase 1 (명세 3.3#1~3) |
| 4 | ★★★ | 한국 상품 옵션별 가격 스크래퍼 (Playwright 옵션 클릭 → DOM) | Phase 2 (명세 3.3#7) |
| 5 | ★★ | 사장님 검수 UI — accepted 케이스 동일 카테고리 다른 SKU 분리 | Phase 1 잔여 |
| 6 | ★★ | 이미지 매칭 프롬프트 재작성 + 임계값 0.85 (양극화 완화) | Phase 1 잔여 |
| 7 | ★★ | 번역 후처리 사전 50개 (마키시무=맥심 등) | Phase 1 잔여 |
| 8 | ★★ | 배송비 파싱 (무료/유료/조건부) | Phase 2 (명세 3.3#10) |
| 9 | ★★ | 누끼 + 내용물 이미지 분리 (식품·화장품 한정) | Phase 2 (명세 3.3#6) |
| 10 | ★★ | 시트 인라인 수정 → 마진 즉시 재계산 | Phase 3 (명세 3.5) |
| 11 | ★ | LLM 카테고리 분류 결함 — 메디큐브/dasique 등 K-뷰티가 「기타」 분류 | Phase 1 분리 이슈 |
| 12 | ★ | OCR 무게 추출 + 200g 룰 | Phase 4 (명세 3.3#13) |
| 13 | ★ | 큐텐 fit 상품명/태그/옵션명 (SEO) 생성 | Phase 4 (명세 3.3#12) |
| 14 | ★ | Windows 작업 스케줄러 등록 | Phase 5 (명세 3.1) |

---

## 9. 의사결정 로그

| 일자 | 결정 | 근거 |
|---|---|---|
| 2026-04-27 | 매칭 1차는 cover 1:1 비전. 정확도 부족 시 2차 임베딩(CLIP). | 사장님 지정. 단순+빠른 시작. |
| 2026-04-27 | 옵션 스크래핑은 한국 상위 10개로 한정. | 사장님 지정. 비용 vs 커버리지 trade-off. |
| 2026-04-27 | 번역 캐시 PK = (source_text, source_lang, target_lang) 별도 `translation_cache` 테이블. | 사장님 지정 (기존 컬럼 직접 박는 안 vs 별도 테이블 안 중 후자). 깔끔성 + 비용 절감. |
| 2026-04-27 | Phase 1 시운전 후 다음 단계 진입 전 BLOCKER 해결 우선. | 시운전 보고서 § 4 — 매칭 정확도가 파이프라인 prerequisite. |
| 2026-04-27 | **BLOCKER 본질 = m07/m08 스크래퍼가 아니라 매칭 후처리 부재.** | naver 정합률 87% (1090건 중 947건). 광고 키워드 도용은 셀러 행위 → 매칭 단계에서 거부해야. |
| 2026-04-27 | **결합 룰 = `text >= 0.3 AND image >= 0.7`** (text_match.py 신규, name_similarity = 자카드 + 부분문자열 보너스). | 보고서 § 4-1 신규 정의. 광고 도용 자동 거부 검증됨. |
| 2026-04-27 | 폴더명 sanitize 보강 = `[`, `]`, `(`, `)`, `{`, `}`, `!`, `?`, `;`, `,`, `$` 추가 제거. | 시운전 § 4#2. 보수적 접근으로 라이브러리 호환성 확보. |
| 2026-04-27 | 상대경로 → 절대경로 변환 (`_run_match_images` 의 `_abs_path`). | image_local_path 가 `image/...` 상대경로 + 백엔드 cwd 미스 → FileNotFoundError 33%. 변환 후 0%. |
| 2026-04-27 | **TEXT_MATCH_THRESHOLD = 0.10** (0.30 → 0.10 완화) | 정상 K-뷰티 시운전: 0.30 에서 accept 0%, 0.10 에서 23%. 코스노리 7/7 정상 매칭 통과. (PHASE1_POSITIVE_TEST § 7) |
| 2026-04-27 | **번역 측 텍스트에 `keyword_kr` 토큰 합치기** (recommendations.py) | 큐텐 ko 가 「코스노리」 같은 브랜드 토큰을 누락하는 케이스 회피. 번역 결함이 매칭 단계에서 치명적이라 매칭 측에서 보완. |
| 2026-04-27 | translate.py JSON 파싱 폴백 제거 (실패 시 None) | 달바 케이스 — `{"ko": "..."` raw 가 ko 컬럼에 박힘. raw 첫 줄 폴백이 결함. 향후 깨진 ko 는 reset + 재번역 필요. |
| 2026-04-27 | jp_ko_translation.txt 강화 — 「브랜드명 반드시 포함」 + 중국어 한자 사용 금지 | 코스노리/qwen2.5:7b 의 브랜드 누락 + 한자/중국어 혼입 결함. 다음 번역부터 적용. |
| 2026-04-28 | **TRANSLATE_MODEL = ollama:qwen3:14b** (qwen2.5:7b → qwen3:14b) | 진단 (DIAGNOSIS_KANA_BRAND.md): 7b 가나 잔존 80%, qwen3:14b 0%. 재번역 후 잔존 189→38 (-80%), accept 26→35 (+9). |
| 2026-04-28 | translate.py max_tokens 512 → 2048 | qwen3:14b reasoning 토큰을 num_predict 안에 포함 → 512 부족 시 빈 응답. |
| 2026-04-28 | **BRAND_AUTO_ADD_THRESHOLD = 0.85** (0.9 → 0.85) | 신규 브랜드 자동 추가 비율 ↑. 검수 큐 거치므로 위험 X. |
| 2026-04-28 | brands whitelist 시드 10개 추가 (코스노리/달바/라운드랩/바이오던스/하파크리스틴/메라메이트/프라이밀/도비아/짱구/코스노리이지브로우) | 자주 등장 브랜드 1차 매칭 → LLM 비용 ↓. (DIAGNOSIS § 2-1) |
| TBD | 결합 룰 임계값 (0.3 / 0.7) 확정 — 정상 K-뷰티 시운전 후 조정. | 사장님 결정 필요. |
| TBD | 「マキシム=맥심」 등 표기 사전 시드 50개. | 사장님 검수 필요. |
| TBD | 세트 제안 룰 — 묶음 개수가 항상 3인지, 큐텐 set_count 따라가는지. 「2만원 이하」 = 환산 KRW. | 사장님 결정 필요. |
| TBD | 이미지 매칭 모델 후보 비교 (qwen2.5-vl vs minicpm-v vs gemini). | 시운전 후 결정. |
| TBD | 카테고리 일치 검사를 결합 룰에 추가할지 (큐텐 category_inferred ↔ 한국 추론 카테고리). | 정상 시운전 결과 보고 결정. |
