# Qoo10 키워드 추출기 — 현재 상황 (2026-04-28)

VBA → Python(FastAPI) + React 재구축. 두 PC(메인 + Tailscale 노트북) 같은 Supabase 공유.
실행: `start.pyw` 더블클릭 → `localhost:8000` (CMD 없음, --reload 없음).

## 7단계 자동화 파이프라인 진척

| # | 단계 | 진척 | 비고 |
|---|---|---|---|
| 1 | 키워드 추출 스케쥴링 | 100% | Windows 작업 스케줄러 + Chrome 디버그 자동시작 (W-1/W-2) |
| 2 | 임계점 자동 필터 | 100% | UserData 슬라이더 임계값 (`/settings`) |
| 3-1 | 큐텐→한국 매칭 (번역+이미지+텍스트) | 95% | R-2 1:N + 결합 룰 (text & image AND) |
| 3-2 | 브랜드 키워드 확장 | 95% | R-3 야간 통합 (Q+S-1+R-2 자동 체인) |
| 4 | 옵션별 가격 (한국 상세 진입) | 85% | CDP attach 봇 우회 (V-1) + dropdown 트리거 (BB-1) |
| 4-2 | 배송비 파싱 | 75% | dt/dd selector + body fallback + parser 7 케이스 통과 (CC-1) |
| 5 | 누끼+내용물 OCR | 90% | EasyOCR 기반 set_count cover OCR 폴백 (M-3) |
| 6 | 상품시트 통합 + 실시간 재계산 | 95% | accepted (matched) 토글 추가 (AA-1) |
| 7 | OCR + 큐텐 fit 콘텐츠 | 100% | qoo10_title_jp/tags/option_name/marketing 자동 |

**종합: 약 91%** (코드 단위. 야간 실가동 + 옵션/배송 검증 후 최종 측정)

## 야간 자동화 흐름 (`automation/daily_workflow.py`)

```
STEP 1     헬스체크 + 디버그 Chrome 9222 자동 점검 (없으면 launch)
STEP 2     로그인 상태
STEP 3     트렌드 키워드 수집 (M02, 비딩 포함)
STEP 3.5   LLM 카테고리+브랜드 분류        ENABLE_LLM_CATEGORY=1
STEP 4     자동 필터 (UserData 임계값/카테고리)
STEP 5     한국 상품 수집 (쿠팡+네이버+큐텐)
STEP 5.5   큐텐 set_count 추출            ENABLE_SET_COUNT_EXTRACTION=1
STEP 5.7 ★ 브랜드 키워드 확장 (Phase 1-D)  ENABLE_BRAND_EXPAND=1
STEP 5.8 ★ 확장 keyword 한국 검색          ENABLE_EXPANDED_SEARCH=1
STEP 5.9   한국 상품 이미지 다운+비전+폴더링  ENABLE_DOMESTIC_IMAGES=1
STEP 5.95★ 큐텐↔한국 cover 1:N 매칭         ENABLE_MATCH_IMAGES=1
STEP 6     추천 자동 빌드 (마진 — set_count 단가 환산)
STEP 6.5   set_count 비전 검증 (마진≥N%)   ENABLE_SET_COUNT_VERIFY=1
```

★ = 2026-04-28 R-3 통합 (이전엔 수동 트리거).

## 작업 스케줄러 등록 (한 번)

```powershell
cd C:\Users\Admin\qoo10-keyword-extractor\automation
powershell -ExecutionPolicy Bypass -File .\setup_scheduler.ps1 -Time "03:00" -IncludeChromeDebug
# 매일 03:00 자동 실행 + 사용자 로그인 1분 후 디버그 Chrome 자동 시작

Get-ScheduledTask -TaskName 'Qoo10DailyWorkflow' | Get-ScheduledTaskInfo
```

## 검수 흐름 (출근 후)

1. `http://localhost:8000/api/recommend/auto-collected/2026-04-28` (날짜 변경 가능)
2. 우측 상단 **`accepted (매칭 통과)만 보기`** 체크박스로 R-2 통과한 후보만 필터
3. 무게 입력 → 마진 실시간 재계산 → 체크 → **시트로 보내기**
4. `/recommend-products` 페이지에서 product_sheet 머지 결과 확인 → 큐텐 export

## 봇 차단 우회 — 사용자 Chrome attach

쿠팡 vp/products / 스마트스토어 captcha — 사용자가 띄운 디버그 Chrome 에 백엔드가 attach (CDP 9222).

```
automation\launch_chrome_debug.bat 더블클릭   # 즉시 띄우기
또는 setup_scheduler.ps1 -IncludeChromeDebug 로 부팅 자동 시작
```

별도 프로필 (`%USERPROFILE%\qoo10-chrome-debug-profile`) — 평소 Chrome 안 닫아도 OK.
첫 실행 시 그 창에서 네이버/쿠팡 로그인 → 다음부터 쿠키 누적 (captcha 거의 0).

## 시운전 명령 (단계별)

```bash
# 1) 카테고리+브랜드 분류
python automation/trigger_classify.py --date 2026-04-28

# 2) 큐텐 상품명 jp→ko 번역
python automation/trigger_translate.py --limit 20

# 3) 큐텐 set_count 추출 (정규식 → ★ cover OCR → LLM)
python automation/trigger_set_count.py --date 2026-04-28

# 4) 브랜드 키워드 확장 (Phase 1-D)
python automation/trigger_brand_expand.py --date 2026-04-28

# 5) 확장 keyword 한국 검색
python automation/trigger_expanded_search.py

# 6) 큐텐 콘텐츠 생성 (title_jp/tags/option_name/marketing)
python automation/trigger_qoo10_content.py --date 2026-04-28

# 7) 한국 상품 이미지 다운+비전
python automation/trigger_domestic_images.py --date 2026-04-28

# 8) 큐텐↔한국 1:N 매칭 (R-2)
python automation/trigger_match_images.py --date 2026-04-28 --top 3

# 9) 한국 상품 옵션/배송비/추가이미지 채우기
python automation/trigger_domestic_details.py --date 2026-04-28           # api_only (빠름)
python automation/trigger_domestic_details.py --date 2026-04-28 --scrape  # 디버그 Chrome 진입 (느림, 정확)
```

## 핵심 모듈/DB

**LLM 인프라** (`backend/app/services/llm/`)
- `category.py` 카테고리 분류 (6분류 + 기타)
- `brand.py` 브랜드 판별 + 자동 추가 (DB whitelist + LLM, ★ aliases JSON)
- `set_count.py` 묶음 추출 (정규식 + ★ cover OCR + LLM)
- `vision.py` 이미지 점수 + 패키지 카운트
- `translate.py` 일본어 → 한국어 번역 (qwen3:14b + 폴백 체인 + jp_kana_to_ko 후처리)
- `text_match.py` 토큰 자카드 + 부분문자열 (LLM 호출 0)
- `image_match.py` 두 이미지 1:1 비교
- `brand_expand.py` 브랜드 확장 (큐텐 product_name → specific keyword 3-5개)
- `qoo10_content.py` 큐텐 등록용 SEO 콘텐츠 생성

**OCR** (`backend/app/services/ocr.py`) — EasyOCR Reader 싱글톤, 2단계 전처리

**모델 라우팅** (`.env` `<DOMAIN>_MODEL=provider:model`) — 자세한 변수는 `.env.example`

**DB (Supabase Postgres)** — `_migrate_add_columns` 자동 마이그레이션
- `keywords` + category_inferred / is_brand / brand_kr/jp/en
- `qoo10_products` + set_count_* / product_name_ko / qoo10_title_jp/tags/option_name/marketing
- `domestic_products` + image_local_path / image_score_* / shipping_kind/amount/threshold / detail_scraped_at / detail_image_paths / weight_g / weight_source
- `domestic_product_options` (1:N — option_name/option_price_krw/in_stock)
- `brands` + ★ **aliases JSON** (다중 표기 — 달바=다루바=dAlba=ダルバ)
- `translation_cache` (PK source_text+source_lang+target_lang)
- `domestic_match_candidates` (qoo10_id/domestic_id/image_score/text_score/decision)
- `expanded_keywords` (parent_jp → specific keyword_kr 1:N)

## 검증된 시간 (4/25 큐텐 1086장 / 425 unique)

- 카테고리+브랜드 분류 425 unique: ~9분 (qwen2.5:14b)
- set_count 추출 688 unique: ~4분 (정규식+LLM. M-3 OCR 폴백 추가 시 regex miss 케이스만 +1초/장)
- 이미지 처리 1086장: ~37분 (minicpm-v:8b 1.7초/장)

## 알려진 이슈

- **백엔드 모듈 reload X**: 코드 변경 후 PowerShell `Get-NetTCPConnection -LocalPort 8000 -State Listen | %{Stop-Process -Id $_.OwningProcess -Force}` + `start.pyw` 재시작 필수
- **Windows asyncpg + SSL traceback**: `_sync.run_sync()` SelectorEventLoop + engine.dispose
- **CMD cp949**: trigger 스크립트 stdout 시작 시 `sys.stdout.reconfigure(encoding="utf-8")`
- **ollama 비전 매칭**: 모델 이름에 `vl/vision/llava/minicpm-v/moondream/gemma3` 키워드 필수 — 새 비전 모델 추가 시 `ollama_client.py` 키워드 list 확장
- **minicpm-v 한국 화장품 인식 약점**: 메디큐브/투에이엔 등 점수 0 빈도 — 향후 qwen2.5-vl 시도 또는 prompt 보완

## 최근 작업 (2026-04-28, 13 commit)

핵심 흐름 강화:
- R-3 daily_workflow STEP 5.7~5.95 통합 (brand_expand → expanded_search → match_images)
- 검수 UI: accepted (matched)만 보기 토글

번역/매칭 정확도:
- Brand.aliases JSON 컬럼 + 시드 6개 (달바=다루바=dAlba=ダルバ 등)
- 카나 잔존 차단 — brand_expand/translate `_has_residual_kana` + 폴백 강제
- text_match STOPWORDS 30+ — 공구/포상/선물/체험/미안기/취급/스킨 등 SEO 광고 노이즈
- brand_expansion prompt — 출력 keyword 에 브랜드 토큰 강제 (사장님 우려 케이스 fix)
- jp_ko_translation prompt — 인명 음역 룰 (장원영→ジャンウォニョン, NOT ヤジン)
- qoo10_content prompt — K-pop 인명 음역 + 포토카드→フォトカード 정확 표기

스크래퍼:
- 옵션 selector 보강 — dropdown 트리거 + role=listbox + dedup (BB-1)
- 배송비 selector dt/dd + body fallback + parser 7/7 (CC-1)
- m08_naver: 카탈로그 후순위 + m_domestic_details NAVER fetcher 가 catalog→seller redirect (HH-1)
- M-3 set_count cover OCR 폴백 (regex miss → image OCR → 정규식 재시도)

## 검증된 효과 (4/28)

- 매칭 accepted: 35/100 (4/27) → **63/100** (4/28 1차) → 47/100 (정리 후, 더 정밀)
- expanded keyword 카나 잔존: 2건 → **0건**
- expanded keyword 브랜드 누락: 9건 → **0건** (정리 + prompt 강화)
- 옵션 다양화: dropdown 트리거 효과로 **9개 잡힌 케이스** 등장
- 배송비: unknown → conditional/paid 정상 파싱
- 인명: ヤジン/ポトカード 의역 → ジャンウォニョン/フォトカード 정확

## 우선순위 (다음)

1. 내일 03:00 야간 자동화 실가동 — 텔레그램 알림으로 R-3 흐름 검증
2. 사장님 검수 별도 페이지 (현재는 토글 — 명세 확정 시)
3. minicpm-v → qwen2.5-vl 교체 시도 (한국 화장품 vision 약점)
4. 폴더 다중 저장 (cover.jpg overwrite 방지 — 같은 product_name 여러 행)
5. 야간 자동화 시간 03:00 → 06:00 이전 검토 (사장님 captcha 즉시 풀이 가능 시간)
