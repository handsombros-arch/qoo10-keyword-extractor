# 엘비텐 (LV10) — 현재 상황 (2026-05-02)

VBA → Python(FastAPI) + React 재구축. 두 PC(메인 + Tailscale 노트북) 같은 Supabase 공유.
실행: `start.pyw` 더블클릭 → `localhost:8000` (CMD 없음, --reload 없음).

## 7단계 자동화 파이프라인 진척

| # | 단계 | 진척 | 비고 |
|---|---|---|---|
| 1 | 키워드 추출 스케쥴링 | 100% | run_nightly + watchdog (R-4) |
| 2 | 임계점 자동 필터 | 100% | UserData 슬라이더 임계값 (`/settings`) |
| 3-1 | 큐텐→한국 매칭 (번역+이미지+텍스트) | 95% | R-2 1:N + 결합 룰 (text & image AND) |
| 3-2 | 브랜드 키워드 확장 | 95% | R-3 야간 통합 + R-5 M05 다양성 |
| 4 | 옵션별 가격 (한국 상세 진입) | 85% | CDP attach 봇 우회 + dropdown 트리거 (BB-1) |
| 4-2 | 배송비 파싱 | 75% | dt/dd selector + body fallback + parser 7 케이스 (CC-1) |
| 5 | 누끼+내용물 OCR | 90% | EasyOCR 기반 set_count cover OCR 폴백 (M-3) |
| 6 | 상품시트 통합 + 실시간 재계산 | 95% | accepted 토글 + R-7 등록상태 토글 |
| 7 | OCR + 큐텐 fit 콘텐츠 | 100% | qoo10_title_jp/tags/option_name/marketing 자동 |

**종합: 약 91%** (코드 단위. R-6 자동화 범위 축소 후 매칭/이미지/auto-build 는 사장님 수동)

## 야간 자동화 흐름 (`automation/run_nightly.py` → `daily_workflow.py`)

**현재 모드: `AUTOMATION_MODE=keyword_only` (R-6, 2026-05-01 결정)**

```
STEP 1     헬스체크 + 디버그 Chrome 9222 자동 launch
STEP 2     로그인 상태 (큐텐/네이버 API/CDP/Naver 세션 디스크 검사)
STEP 3     트렌드 키워드 수집 (01.종합 + 03.뷰티&화장품 + 07.식품, 비딩 포함)
STEP 3.5   LLM 카테고리+브랜드 분류        ENABLE_LLM_CATEGORY=1
STEP 4     자동 필터 (UserData 임계값/카테고리)
STEP 4.5 ★ M05 유사/연관 키워드 (R-5)      ENABLE_RELATED_KEYWORDS=1
              parent ≤ 33, RELATED_KEYWORDS_MAX_PER_PARENT=15
              결과: expanded_keywords INSERT
              ↑ keyword_only 모드는 여기서 종료 (R-6)

──────── 이하 STEP 5+ 는 사장님 수동 (R-6) ────────
STEP 5     한국 상품 수집 (쿠팡+네이버+큐텐)
STEP 5.5   set_count 추출 (정규식 + cover OCR + LLM)
STEP 5.7   브랜드 키워드 확장 (LLM)
STEP 5.8   확장 keyword 한국 검색
STEP 5.9   한국 이미지 다운+비전+폴더링
STEP 5.95  큐텐↔한국 1:N 매칭 (cover image + text)
STEP 6.0   큐텐 SEO 콘텐츠 (qoo10_title/tags/marketing)
STEP 6     추천 자동 빌드 (마진 — set_count 단가 환산)
STEP 6.5   set_count 비전 검증 (마진≥N% 만)
STEP 6.6   매칭 retry — alt 키워드 의역 (HHH-1)
STEP 6.7   candidate 폴더 생성 (image/{date}/N. <kw>/)
STEP 7     Quality 임계값 auto-tune (KKK-1 C)
```

**`full` 모드로 환원**: `.env` 에 `AUTOMATION_MODE=full` 추가 후 backend 재시작.

## R-4 자가 진단/수정 시스템 (2026-05-01 추가)

`run_nightly.py` 진입점이 다음을 통합 처리:

```
run_nightly.py {today}
  ├─ 1차 daily_workflow.py 실행 (rc≠0,2,3 → 60초 후 재시도 1회)
  │   └─ wait_task watchdog: 5회 폴링 fail → /api/auth/status →
  │                            죽음 → 8000 포트 kill + start.pyw 재실행 + 30초 대기
  │   └─ STEP 4 = 0 진단: loose 임계값 재호출 → 메타 누락/임계값 과다 분기
  ├─ verify_run.py {date} --recover (C1~C6 6개 점검 + 누락 STEP 자동 회복)
  └─ morning_report.py (텔레그램 + 슬랙)
```

`recover.py` 사용:
```bash
python automation/recover.py 2026-05-02              # 자동 감지 + 누락 STEP 실행
python automation/recover.py 2026-05-02 --only 6,6.7
python automation/recover.py 2026-05-02 --from-step 6
python automation/recover.py 2026-05-02 --dry-run
```

`verify_run.py` mode 인지 — `keyword_only` 면 C3+ (auto-build/폴더/SEO) 검증 스킵.

## 작업 스케줄러 등록

```powershell
cd C:\Users\Admin\qoo10-keyword-extractor\automation
# run_nightly 사용 (기본)
powershell -ExecutionPolicy Bypass -File .\setup_scheduler.ps1 -Time "00:30"
# daily_workflow 직접 (롤백)
powershell -ExecutionPolicy Bypass -File .\setup_scheduler.ps1 -Time "00:30" -UseLegacyWorkflow
```

3개 task 등록:
- `Qoo10ChromeDebug` — AtLogOn + AtStartup, 9222 자동 시작
- `Qoo10DailyWorkflow` — 매일 00:30 (현재 NextRun 기준)
- `Qoo10MorningReport` — 매일 08:00, 텔레그램+슬랙

## 검수 흐름 (출근 후)

R-6 keyword_only 모드라 야간 자동화는 **키워드 RD까지만**. 이후는 사장님 직접:

1. `http://localhost:8000/api/recommend/auto-collected/{date}` (날짜 선택)
2. 우측 상단 **`accepted (매칭 통과)만 보기`** 토글
3. **R-7 등록상태**: 미정/등록중/등록완료 dropdown (좌측 pinned, 색깔 표시)
4. 무게 입력 → 마진 실시간 재계산 → 체크 → **시트로 보내기**
5. `/recommend-products` 페이지에서 product_sheet 머지 결과 → 큐텐 export
6. **URL→SEO 재생성** (4/30 신규): SheetRowDetailPanel 의 [URL 재생성] 버튼
   → naver_fetch_v2 + OCR + SEO + JP detail + 진행률 폴링

## R-7 시트 등록 상태 토글 (2026-05-01)

- `SheetRow.registration_status` 필드 (`'미정' | 'in_progress' | 'completed'`)
- `SheetRow.registered_at` (자동기록), `qoo10_product_id` (선택)
- 좌측 pinned 컬럼 "등록상태" — agSelectCellEditor + 색깔
- 상단 toolbar 등록상태 필터 (전체/진행중/미정/등록중/등록완료) localStorage 저장
- 파일: `frontend/src/store/productSheet.ts`, `frontend/src/pages/RecommendProductsPage.tsx`

## 봇 차단 우회 — 사용자 Chrome attach

쿠팡 vp/products / 스마트스토어 captcha — 사용자 디버그 Chrome 에 백엔드 attach (CDP 9222).

```
automation\launch_chrome_debug.bat            # 즉시 띄우기
automation\open_naver_login_chrome.bat        # 네이버 1회 로그인 setup
```

별도 프로필:
- `%USERPROFILE%\qoo10-chrome-debug-profile` (큐텐/쿠팡)
- `data/naver-browser-profile` (네이버 detail v2 — 4/30 신규)

**Chrome 147+ 보안 차단**: 메인 Default 프로필 + `--remote-debugging-port` → CVE 보안 패치로 silent 무시. **별도 user-data-dir 필수**.

## Naver 세션 헬스체크 (2026-04-30 추가)

`backend/app/services/naver_session_check.py` + `GET /api/products/naver-session-check`:
- NID_AUT/NID_SES 디스크 검사 + days_left 계산
- 만료/누락 → 자동화 즉시 중단 + 텔레그램·슬랙 알림 (level=auth)
- D-7 임박 → warn 알림 (자동화는 진행)
- 현재 만료: 2026-05-30 (29일). 5/23 부터 D-7 알림.

**Naver 5/30 만료 = "로그인 유지" 30일** (1년 아님). 만료 시 `open_naver_login_chrome.bat` 로 1회 재로그인.

## 시운전 명령 (단계별)

```bash
python automation/trigger_classify.py --date 2026-05-02
python automation/trigger_translate.py --limit 20
python automation/trigger_set_count.py --date 2026-05-02
python automation/trigger_brand_expand.py --date 2026-05-02
python automation/trigger_expanded_search.py
python automation/trigger_qoo10_content.py --date 2026-05-02
python automation/trigger_domestic_images.py --date 2026-05-02
python automation/trigger_match_images.py --date 2026-05-02 --top 3
python automation/trigger_domestic_details.py --date 2026-05-02 --scrape
python automation/trigger_extract_weights.py
python automation/trigger_verify_set_count.py
```

`backend/scripts/`: `seed_brands.py`, `update_brand_aliases.py [--kr X --add Y Z]`, `test_llm.py`.

## 핵심 모듈/DB

**LLM 인프라** (`backend/app/services/llm/`)
- `category.py` 카테고리 분류 (6분류 + 기타)
- `brand.py` 브랜드 판별 + 자동 추가 (DB whitelist + LLM, aliases JSON)
- `set_count.py` 묶음 추출 (정규식 + cover OCR + LLM, returns tuple `(count, source)`)
- `vision.py` 이미지 점수 + 패키지 카운트 (+ 비용 보호 `VISION_DAILY_BUDGET_USD=2.0`)
- `translate.py` 일본어 → 한국어 (qwen3:14b + 폴백 + jp_kana_to_ko 후처리)
- `text_match.py` 토큰 자카드 + 부분문자열 (LLM 호출 0)
- `image_match.py` 두 이미지 1:1 비교
- `brand_expand.py` 브랜드 확장 (큐텐 product_name → specific keyword 3-5개)
- `qoo10_content.py` 큐텐 등록용 SEO 콘텐츠 (패턴 A/B/C/D 분산 + 약사법 회피)
- `qoo10_jp_detail.py` JP 상세 (qwen2.5:14b 분리 — qwen3 thinking 토큰 truncate 회피)
- `cover_describe.py` 큐텐/한국 cover 이미지 묘사 (qwen2.5vl, GGG-1)

**ULTRA lenient JSON 파서** (4/30, `qoo10_jp_detail.py`): 4단계 — 엄격 → smart-quote/trailing-comma fix → incremental } trim → raw 저장 (`backend/logs/llm_failures/`).

**자동 매칭 학습 (4/30)**:
- `auto_learning.py` + `match_quality.py` + `match_retry.py` (HHH-1 alt keyword)
- `user_corrections` 테이블 (FFF-2) — 사장님 swap/reject INSERT

**OCR** (`backend/app/services/ocr.py`) — EasyOCR Reader 싱글톤, 2단계 전처리

**naver_fetch_v2** (4/30, Playwright):
- 1순위 CDP 9222 attach
- 2순위 persistent context (`data/naver-browser-profile`)

**모델 라우팅** (`.env` `<DOMAIN>_MODEL=provider:model`) — 자세한 변수는 `.env.example`

**현재 모델 (모두 ollama 로컬, RTX 5080)**:
```
TRANSLATE_MODEL=ollama:qwen3:14b  + TRANSLATE_FALLBACK_MODELS=qwen2.5:14b,qwen2.5:7b
CATEGORY_MODEL=ollama:qwen2.5:14b
BRAND_MODEL=ollama:qwen2.5:14b
SET_COUNT_MODEL=ollama:qwen2.5:7b
VISION_MODEL=ollama:qwen2.5vl:7b   # GGG-1 — minicpm-v 한국 화장품 약점 보완
IMAGE_MATCH_MODEL=ollama:minicpm-v:8b  IMAGE_MATCH_THRESHOLD=0.7
TEXT_MATCH_THRESHOLD=0.10
QOO10_CONTENT_MODEL=ollama:qwen3:14b
QOO10_JP_DETAIL_MODEL=ollama:qwen2.5:14b   # qwen3 thinking 토큰 truncate 회피
BRAND_EXPAND_MODEL=ollama:qwen3:14b
BRAND_AUTO_ADD_THRESHOLD=0.85
```

**DB (Supabase Postgres)** — `_migrate_add_columns` 자동 마이그레이션
- `keywords` + category_inferred / is_brand / brand_kr/jp/en (lookup_date 기준)
- `qoo10_products` + set_count_* / product_name_ko / qoo10_title_jp/tags/option_name/marketing / cover_description / qoo10_jp_detail
- `domestic_products` + image_local_path / image_score_* / shipping_kind/amount/threshold / detail_scraped_at / detail_image_paths / weight_g / weight_source / cover_description
- `domestic_product_options` (1:N — option_name/option_price_krw/in_stock)
- `brands` + **aliases JSON** (다중 표기 — 달바=다루바=dAlba=ダルバ)
- `translation_cache` (PK source_text+source_lang+target_lang)
- `domestic_match_candidates` (qoo10_id/domestic_id/image_score/text_score/decision)
- `expanded_keywords` (parent_jp + keyword_jp UNIQUE — R-3/R-5 통합)
- `user_corrections` (4/30 — 자동 매칭 학습 입력)

## 검증된 시간 (4/25 큐텐 1086장 / 425 unique)

- 카테고리+브랜드 분류 425 unique: ~9분 (qwen2.5:14b)
- set_count 추출 688 unique: ~4분 (정규식+LLM. M-3 OCR 폴백 추가 시 regex miss 케이스만 +1초/장)
- 이미지 처리 1086장: ~37분 (minicpm-v:8b 1.7초/장)
- domestic_details api_only 19건: ~5초. scrape 모드 10건: ~2분 (CDP attach)
- **5/2 keyword_only 전체: 20분 24초** (트렌드 670 + 분류 435 + 필터 + M05 85)

## 알려진 이슈 / 운영 메모

- **백엔드 모듈 reload X**: `Get-NetTCPConnection -LocalPort 8000 -State Listen | %{Stop-Process -Id $_.OwningProcess -Force}` + `start.pyw` 재시작 필수
- **Windows asyncpg + SSL traceback**: `_sync.run_sync()` SelectorEventLoop + engine.dispose
- **CMD cp949**: trigger 스크립트 stdout 시작 시 `sys.stdout.reconfigure(encoding="utf-8")`
- **ollama 비전**: 모델 이름에 `vl/vision/llava/minicpm-v/moondream/gemma3` 키워드 필수 — 새 비전 모델 추가 시 `ollama_client.py` 키워드 list 확장
- **morning_report 로그 path 오인식 (5/2 발견)**: 로그 파일은 정상 생성되는데 working dir 차이로 "로그 없음" 텔레그램 표시 — minor
- **`keywords` 테이블 lookup_date+keyword_jp UNIQUE 제약 없음 (5/2 발견)**: 같은 키워드 두 행 INSERT 가능. 5/2 필터 결과에 중복 보임. 운영 영향은 작음
- **5/2 keywords 0건 사고**: ID 시퀀스 last_value=20416, 자식 테이블(qoo10_products 5889 등) 멀쩡 → 누군가 DELETE/TRUNCATE 추정. 사장님 결정으로 복구 안 함, 5/2부터 재수집

## 보류·구현 난제 (2026-05-02)

### A. 의도적 보류 (정책·시기 대기)

| 항목 | 사유 | 해제 조건 |
|---|---|---|
| **STEP 5+ 야간 자동화** (매칭/이미지/auto-build) | R-6 (5/1 사장님 결정). hang 빈도·정합도 부족 → R-8 확장으로 fetch 안정성은 해소 | 매칭 정합도 개선 (GGG-2) + R-8 STEP 5 통합 (Phase 3) 후 재가동 검토 |
| **R-8 options/shipping 자동화** | Naver SPA 가 client-side fetch 후 채우는 sub-store. polling 으론 못 잡음 | Naver smartstore API 직접 호출 (network 분석 1~3시간). 현재 시트 수동 입력으로 충분 |
| **GGG-2 cover_description 매칭 룰 분석** | corrections·description 데이터 부족 (5/2 기준 0건) | 5/6 이후 1주 누적 후 트리거 |
| **사장님 검수 별도 페이지** | 명세 미확정. 현재는 토글로 충분 | 명세 확정 시 |
| **자동 학습 KKK-1 자동 반영 루프** | full mode 종속. R-6 동안 데이터만 누적 | full mode 복귀 시 동시 부활 |
| **`google-genai` 마이그레이션** | 클라우드 LLM 사실상 미사용 | deprecated 경고 시급해질 때 |
| **PC 끄고 자동화 / vercel 배포** | Playwright + 로컬 ollama + CDP 9222 + 야간 20분 — 함수 환경 부적합 | 구조 결정 필요 — 현 상태에서는 PC 상시 가동이 답 |

### B. 외부·구조 의존 (단독 해결 어려움)

| 항목 | 한계 |
|---|---|
| **큐텐 트렌드 historical 조회 불가** | 사이트 자체가 과거 데이터 안 줌. 5/2 사고 시 복원 불가능했던 근본 원인 |
| **큐텐 일시 장애 (4/30, 5/2 새벽)** | 12 카테고리 동시 0건 후 후일 정상 — 큐텐 측 이슈. 자동화는 재시도로 흡수 |
| **Chrome 147+ 메인 Default 프로필 9222 차단** (R-8 으로 우회) | CVE 보안 패치. R-8 크롬 확장은 9222 미사용 → 메인 Chrome 직접 사용 가능 |
| **Naver 세션 false negative — 두 흐름의 모순** (5/2 Phase 0 검증으로 정체 확정 → R-8 으로 해소) | `naver_session_check.py` (STEP 2 헬스체크) 는 `data/naver-browser-profile/Default/Network/Cookies` 디스크 검사 → 매일 "OK 27일 남음" 통과. 그러나 `naver_fetch_v2.py` 1순위는 사장님 **메인 Chrome 9222** attach (다른 프로필) → 거기 Naver 로그인 X → 로그인 redirect 실패. 5/2 측정에서 5/5 모두 fail. **시트 [URL 재생성]·STEP 5 한국 상세 수집이 실질 작동 안 했음**. R-8 크롬 확장 도입으로 메인 Chrome 1개 사용 → 모순 자체 해소. |
| **Naver 세션 30일 한정 ("로그인 유지" 30일)** (R-8 으로 해소) | R-8 은 사장님 메인 Chrome 세션 사용 → 사장님이 평소 사용하는 한 만료 X. `open_naver_login_chrome.bat` 불필요 |
| **OS sleep → daily_workflow silent kill** | 5/1 사고. Task Scheduler "Wake the computer to run this task" 활성화 필요 (사용자 환경 설정) |
| **봇 차단 우회 — CDP attach 의존** (R-8 으로 부분 해소) | 네이버는 R-8 확장으로 대체 (CDP X). 큐텐 트렌드(STEP 3) / 쿠팡 captcha 는 여전히 9222 사용. 메인 Chrome 켜둠 필요 |

### C. 기술 난제 (해결 가능하지만 우선순위·시간)

| 항목 | 현 상태 | 해결안 |
|---|---|---|
| **task_manager DB 영구화 X** | in-memory. backend 재시작 시 STEP 5.95 (1~2시간) loss 가능 | `tasks` 테이블 + 진행률 영속화 |
| **STEP 6.6 retry 동시성 hang** | STEP 6.0 가 ollama 점유 시 retry 한 키워드에서 hang | 직렬 실행 또는 retry timeout |
| **무게(weight_g) 자동 추출 사실상 X** | 도메스틱 무게/용량 표기 변종 너무 많음. 검수 시 사장님이 매번 수동 입력 — 시간 가장 많이 잡아먹는 손작업일 가능성 | OCR + LLM 추출 + 신뢰도 임계값 (Phase 4-A 부활) |
| **set_count 정확도** | M-3 OCR 폴백 있어도 5/6 묶음 오인식 → 환상 마진 5000% 빈도 | 비전 검증 (STEP 6.5) full mode 한정. keyword_only 에선 검수 의존 |
| **카타카나 신생 브랜드 alias 자동 등록 X** | brand_expand 가 keyword 만 만듦. alias 시드는 수동 (`update_brand_aliases.py`) | 매칭 실패 + corrections swap 패턴에서 alias 자동 추출 |
| **user_corrections → 룰 자동 반영 루프 X** | match_quality / match_retry 데이터 누적되지만 임계값/룰 자동 피드백 없음 | GGG-2 분석으로 수동 반영 시작 → 검증되면 자동화 |
| **옵션 dropdown / 배송비 변종 셀러** | BB-1·CC-1 핵심 케이스만. JS 동적 옵션 / 모달 배송정책 등 fallback 약함 | 셀러별 케이스 추가 (점진적) |
| **이미지 매칭 cascade 4시간 timeout** | 4/28 야간 cascade ON 시 5.95 매칭 3000+ 쌍 → 4시간 → 비활성. 한국 화장품 false reject 약점은 검수로 보완 | 매칭 모델 교체 (qwen2.5-vl) 또는 batch 처리 |
| **minicpm-v 한국 화장품 약점** | 메디큐브/투에이엔 score 0 빈도. cover_describe 만 qwen2.5vl 로 보완 (GGG-1) | image_match 자체를 qwen2.5-vl 로 교체 시도 |
| **마케팅 포인트 OCR 정확도 미측정** | 네이버 detail 이미지 위주 → OCR 의존 → 품질 상한 불명 | 샘플 5~10건 측정 (다음 작업 후보) |

## 최근 작업 (2026-04-30 ~ 2026-05-02)

**4/30 (commit a7df8cd)**:
- Naver 세션 헬스체크 + GET /api/products/naver-session-check
- JP detail 모델 분리 (qwen2.5:14b, temperature 0.4→0.2). qwen3 thinking 토큰 truncate 회피
- ULTRA lenient JSON 파서 (`qoo10_jp_detail.py`)
- URL→SEO 재생성 통합 (DDDD-1, HHHH-1): `POST /api/products/regenerate-content-from-url`
- naver_fetch_v2 (CDP attach + persistent context)
- Chrome 147 9222 차단 발견 → naver-browser-profile 별도 user-data-dir 영구 사용 확정
- 사장님 1회 로그인 (`open_naver_login_chrome.bat`)
- SheetRowDetailPanel: URL 재생성 + JP detail UI + 진행률 %
- SEO marketing_points: qoo10-jp-detail-master 가이드 적용 (의태어, 약사법 회피, 패턴 A/B/C/D 분산)
- 자동 매칭 학습 3종 (`auto_learning.py` + `match_quality.py` + `match_retry.py`)

**5/1**:
- **R-4** 자가 진단/수정: `run_nightly.py` + `verify_run.py` + `recover.py` + watchdog
  - 4/29-5/1 3일 연속 hang 사고 후 구축
  - C1~C6 검증 + 누락 STEP 자동 회복
- **R-5** 키워드 다양성: M05 RelatedKeywordScraper STEP 4.5 추가
  - `diagnose_keyword_freshness.py`, `GET /api/keywords/freshness`, `POST /api/keywords/expand-related`
  - jaccard 0.95 (4/29-30) → expanded_keywords 신규 INSERT 200건/일 목표
- **R-6** 자동화 범위 축소: `AUTOMATION_MODE=keyword_only` 기본
  - 키워드 RD (STEP 1~4.5) 까지만. STEP 5+ 는 사장님 수동
  - 매칭/이미지/auto-build 가 자주 hang/실패 → 사장님 결정
- **R-7** 시트 등록 상태 토글: 미정/등록중/등록완료 dropdown + 색깔 + 필터

**5/2**:
- ⚠️ keywords 테이블 0건 사고 발견 — 자식 테이블(qoo10_products 5889 등)은 멀쩡, ID 시퀀스 last_value 20416 흔적
- 03:52 야간 자동화 STEP 3 실패 (큐텐 일시 장애, 4/30과 동일 패턴)
- 16:11 수동 재실행: keyword_only 20분 24초 완주
  - 트렌드 670 / 분류 435 / 필터 통과 20 / M05 확장 85 (parent 39)
- **STEP 3 트렌드 카테고리 디폴트 변경**: `[0]`(전체 12) → `[1, 3, 7]` (01.종합 + 03.뷰티&화장품 + 07.식품). 사장님 사업 영역만 → 시간 1/4
- **R-8 크롬 확장 (qoo10-helper-extension)** — `naver_fetch_v2` 가 거의 깨진 상태(Phase 0 검증: 5/5 fail)였던 것을 해결. 사장님 메인 Chrome 1개 + JSON-LD/`__PRELOADED_STATE__` page-world dump.
  - Phase 0 (backend playwright) 0/5 → Phase 1 (확장 active+polling) **6/8 필드 100%** (product_name, brand, price, cover, category, detail_images)
  - Phase 2: `POST /api/products/regenerate-content-from-url` → `ext_client.fetch_one()` 경유로 변경. 환경변수 `EXT_USE_EXTENSION=true` 기본
  - 시트 [URL 재생성] e2e 검증 완료 (사장님 손에 익힘)
  - 잔여 한계: options/shipping (Naver SPA 가 client-side fetch 후 채우는 sub-store — polling 으론 못 잡음. 사장님 시트 수동 입력 흐름 그대로)

## 우선순위 (다음)

1. **Phase 3 — 야간 자동화 STEP 5 ext_client 통합** (full mode 복귀 시): `daily_workflow.py` STEP 5 한국 상세 수집을 `naver_fetch_v2` → `ext_client.fetch_one` 경유로 변경. R-6 mode 라 미시급
2. **운영 관찰** — 사장님 손작업 며칠 후 셀렉터 깨짐 빈도 / 화면 깜빡임 받아들임 검증
3. **GGG-2 분석** (5/6 이후) — corrections + cover_description 1주 누적 후 매칭 룰 제안
4. **마케팅 포인트 OCR 정확도 측정** — `qoo10-jp-detail-master.md` v1.1 의 OCR 의존성 명시 따라 정량
5. **task_manager DB 영구화** — STEP 5.95 1~2시간 loss 방지
6. **STEP 6.6 retry 동시성 fix** — ollama 직렬 또는 timeout
7. **Task Scheduler "Wake the computer"** — OS sleep 방지
8. minicpm-v → qwen2.5-vl 매칭 교체 시도 (한국 화장품 vision 약점)
9. **시트의 마진/등록 흐름 단순화** — R-7 등록상태 토글 시작점, 158행 누적
10. **R-8 후속**: options/shipping 자동화가 필요하면 Naver smartstore API 직접 호출 (network 분석 1~3시간)
11. `google-genai` 마이그레이션 (deprecated 경고 제거)

---

**버전 히스토리**
- v0.4 (2026-05-02): R-4/5/6/7 + 4/30 작업 + 5/2 사고 반영
- v0.3 (2026-04-29): R-3 + 검수 UI + 옵션/배송 보강
