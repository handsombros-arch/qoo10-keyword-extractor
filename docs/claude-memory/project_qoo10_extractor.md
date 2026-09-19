---
name: Qoo10 키워드 추출기 프로젝트
description: VBA → Python+FastAPI+React. 7단계 약 91% (4/28). Phase 1+1-D (R-3 야간 통합) + Phase 2.5 (CDP attach 봇 우회) + Phase 3 (시트+슬라이더+UserData+accepted 토글) + Phase 4 (무게/큐텐 SEO/엑셀) + Phase 5 (스케줄러). Brand.aliases JSON, 옵션 dropdown 트리거, 배송비 dt/dd fallback, cover OCR set_count.
type: project
originSessionId: 7d5758a7-f9a2-4f8e-893e-325dca02eda7
---
## 프로젝트 위치
- 코드: `C:\Users\Admin\qoo10-keyword-extractor\` (GitHub `handsombros-arch/qoo10-keyword-extractor`, master)
- 실행: `start.pyw` 더블클릭 → `localhost:8000` (CMD 없음, **--reload 없음** — 코드 변경 시 수동 재시작)
- 재시작: `Get-NetTCPConnection -LocalPort 8000 -State Listen | %{Stop-Process -Id $_.OwningProcess -Force}` + start.pyw
- DB: Supabase Postgres (`backend/.env` `DATABASE_URL`)
- 두 PC: 메인 PC + Tailscale 노트북, 둘 다 같은 Supabase 공유

## 7단계 진척 (2026-04-28 기준)

| # | 단계 | % | 키 작업 |
|---|---|---|---|
| 1 | 키워드 추출 스케쥴링 | 100% | W-1/W-2 setup_scheduler + Chrome 디버그 자동시작 |
| 2 | 임계점 자동 필터 | 100% | UserData 슬라이더 (`/settings`) |
| 3-1 | 큐텐→한국 매칭 | 95% | R-2 1:N + 결합 룰 (text & image AND) |
| 3-2 | 브랜드 키워드 확장 | 95% | Q+S+R-2 + R-3 야간 자동 통합 |
| 4 | 옵션별 가격 | 85% | CDP attach + dropdown 트리거 (BB-1) |
| 4-2 | 배송비 | 75% | dt/dd selector + body fallback + parser 7케이스 (CC-1) |
| 5 | 누끼+OCR | 90% | EasyOCR + set_count cover OCR (M-3) |
| 6 | 시트 통합 | 95% | accepted (matched) 토글 (AA-1) |
| 7 | 큐텐 콘텐츠 | 100% | qoo10_title_jp/tags/option_name/marketing 자동 |

## 백엔드 / 프론트
- Backend: FastAPI 0.115 / SQLAlchemy 2.0 (async) / Playwright 1.48 / asyncpg / Pillow / EasyOCR
- Frontend: React 18 + Vite + Tailwind. `npm run build` 후 backend 정적 서빙
- DB 자동 마이그레이션: `main.py` `_migrate_add_columns` (idempotent ALTER)

## ─── AI 추론 인프라 ───────────────────────

**위치**: `backend/app/services/llm/`
**라우팅**: `.env` `<DOMAIN>_MODEL=provider:model`

**현재 모델 (모두 ollama 로컬)**:
```
TRANSLATE_MODEL=ollama:qwen3:14b  + TRANSLATE_FALLBACK_MODELS=qwen2.5:14b,qwen2.5:7b
CATEGORY_MODEL=ollama:qwen2.5:14b
BRAND_MODEL=ollama:qwen2.5:14b
SET_COUNT_MODEL=ollama:qwen2.5:7b
VISION_MODEL=ollama:minicpm-v:8b
IMAGE_MATCH_MODEL=ollama:minicpm-v:8b   IMAGE_MATCH_THRESHOLD=0.7
TEXT_MATCH_THRESHOLD=0.10
QOO10_CONTENT_MODEL=ollama:qwen3:14b
QOO10_JP_DETAIL_MODEL=ollama:qwen2.5:14b   # 4/30 분리 — qwen3 thinking 토큰이 mid-output truncate 유발
BRAND_EXPAND_MODEL=ollama:qwen3:14b
BRAND_AUTO_ADD_THRESHOLD=0.85
```

**Gemini 백업** (사용 안 함, 키 풀 + 자동 페일오버 지원):
- `GEMINI_API_KEYS=key1,key2,key3` 콤마구분
- 무료 티어는 일 20회 (실용성 X) — `gemini-2.5-flash` 만 살아있음

**모듈**:
- `category.py` 6분류 + 기타 (json_mode)
- `brand.py` whitelist DB → LLM → confidence ≥ threshold 면 자동 INSERT (★ aliases JSON 매칭 포함)
- `set_count.py` 정규식 → ★ cover OCR 폴백 → LLM (반환 tuple `(count, source)`)
- `translate.py` jp→ko + 폴백 체인 + jp_kana_to_ko.json 후처리
- `text_match.py` 자카드+부분문자열 (LLM 호출 0)
- `image_match.py` 두 이미지 1:1 비교
- `brand_expand.py` 큐텐 product_name → specific keyword 3-5개
- `qoo10_content.py` 큐텐 SEO 콘텐츠
- `vision.py` + 비용 보호 (`VISION_DAILY_BUDGET_USD=2.0`, jsonl 누적)

## ─── daily_workflow.py STEP (★ = R-3 신규) ──────────

```
STEP 1     헬스체크 + ★ 9222 자동 점검+launch
STEP 2     로그인 상태 (큐텐 + 네이버 API + Chrome9222 + ★ Naver smartstore 세션 — 4/30 추가)
           Naver 세션: naver-browser-profile/Default/Network/Cookies 디스크 검사
           만료/누락 → 자동화 즉시 중단 + 텔레그램/슬랙 알림
           D-7 임박 → warn 알림 (자동화는 진행)
STEP 3     트렌드 키워드 (M02, 비딩 포함)
STEP 3.5   카테고리+브랜드 분류             ENABLE_LLM_CATEGORY=1
STEP 4     자동 필터 (UserData 임계값)
STEP 5     한국 상품 수집 (쿠팡+네이버+큐텐)
STEP 5.5   set_count 추출                  ENABLE_SET_COUNT_EXTRACTION=1
STEP 5.7 ★ 브랜드 키워드 확장               ENABLE_BRAND_EXPAND=1
STEP 5.8 ★ expanded → 한국 검색             ENABLE_EXPANDED_SEARCH=1
STEP 5.9   한국 이미지 다운+비전+폴더링       ENABLE_DOMESTIC_IMAGES=1
STEP 5.95★ 큐텐↔한국 1:N 매칭                ENABLE_MATCH_IMAGES=1
STEP 6     추천 자동 빌드 (단가 환산)
STEP 6.5   set_count 비전 검증 (마진≥N%)    ENABLE_SET_COUNT_VERIFY=1
STEP 6.6 ★ 매칭 retry — alt 키워드 의역      ENABLE_MATCH_RETRY=1 (HHH-1)
            best image_score < 0.5 → LLM 으로 alt keyword_kr 2~3개 →
            Naver 재검색 → 재매칭 → DMC INSERT (source_match_kind='alt_keyword')
            개선 시 auto_build 재실행 (cheapest_domestic 갱신)
```

매일 03:00 작업 스케줄러 자동 실행 (P-1 등록 명령: `setup_scheduler.ps1 -Time "03:00" -IncludeChromeDebug`).

## ─── 자동 필터 ────────────

조건 기본: `competition_max=2.0`, `kr_ratio_min=0.3`, `volume_min=40`. UserData(`/settings`) > .env > 하드코딩.
**brand=1 키워드는 카테고리 화이트리스트 무시** (브랜드 분류 신뢰도 낮아 누락 방지)

## ─── DB 신규 테이블 / 컬럼 ───────────────────────

- **`brands`**: id, kr UNIQUE, jp, en, ★ **aliases JSON** (다중 표기), source, confidence — 시드 50 + 자동 추가 + manual + 4/28 alias 시드 (달바=다루바=dAlba=ダルバ, 메디큐브, 라카, 아누아, 코스노리, 하파크리스틴)
- **`keywords`**: + category_inferred / is_brand / brand_kr/jp/en
- **`qoo10_products`**: + set_count*/product_name_ko + Phase 4-B (qoo10_title_jp/qoo10_tags JSON/qoo10_option_name/qoo10_marketing JSON/qoo10_content_generated_at)
- **`domestic_products`**: + image_*/Phase 2 (shipping_kind/amount/threshold/detail_scraped_at/detail_image_paths) + Phase 4-A (weight_g/weight_source)
- **`translation_cache`** (PK source_text+lang+lang)
- **`domestic_match_candidates`**: qoo10_id/domestic_id/name_score/image_score/decision
- **`domestic_product_options`**: 옵션 1:N
- **`expanded_keywords`**: parent_jp/keyword_jp/keyword_kr/source_count

## ─── 마진 단가 환산 ──────────────────

`unit_price = price_jpy / nullif(set_count, 0)` — 묶음 가격 → 단가. 환상 마진 (5000% 등) 제거.

## ─── CDP attach (사용자 Chrome 봇 우회) ──

- `m_domestic_details.py` _get_user_chrome_context — port 9222
- `automation\launch_chrome_debug.bat` 더블클릭 (또는 setup_scheduler -IncludeChromeDebug 자동)
- 별도 프로필 `%USERPROFILE%\qoo10-chrome-debug-profile`. 평소 Chrome 안 닫아도 OK
- captcha 발생 시 GUI 직접 풀면 자동화 계속

## ─── 검수 흐름 (출근 후) ───────

1. `http://localhost:8000/api/recommend/auto-collected/{date}` → "accepted (매칭 통과)만 보기" 토글
2. 무게 입력 → 마진 실시간 재계산 → 체크 → 시트로 보내기
3. `/recommend-products` → 큐텐 export

## ─── CLI 헬퍼 (automation/) ───

`daily_workflow.py [--dry-run]`, `trigger_classify`, `trigger_translate`, `trigger_set_count`, `trigger_brand_expand`, `trigger_expanded_search`, `trigger_qoo10_content`, `trigger_domestic_images`, `trigger_match_images`, `trigger_domestic_details [--scrape] [--reset]`, `trigger_extract_weights`, `trigger_verify_set_count`.

`backend/scripts/`: `seed_brands.py`, ★ **`update_brand_aliases.py [--kr X --add Y Z]`**, `test_llm.py`.

## ─── 검증된 시간 ────

- 카테고리+브랜드 425 unique: ~9분 (qwen2.5:14b)
- set_count 688 unique: ~4분 (정규식+LLM. M-3 OCR 폴백 추가 시 regex miss 만 +1초/장)
- 이미지 1086장: ~37분 (minicpm-v:8b 1.7초/장)
- domestic_details api_only 19건: ~5초. scrape 모드 10건: ~2분 (CDP attach)

## ─── 4/30 새 작업 (commit a7df8cd) ────

- **Naver 세션 헬스체크**: `backend/app/services/naver_session_check.py` + `GET /api/products/naver-session-check` + daily_workflow `step_login_status` 4번째 체크. NID_AUT/NID_SES 디스크 검사 + days_left 계산. 만료/누락 시 자동화 중단 + 텔레그램·슬랙 알림 (level=auth). D-7 임박 시 warn.
- **Naver 5/30 만료**: 현 NID_AUT/NID_SES persistent=1, expires=2026-05-30 (29일). "로그인 유지" 가 1년 아닌 30일임. 5/23 부터 D-7 알림.
- **JP detail 모델 분리**: `QOO10_JP_DETAIL_MODEL=ollama:qwen2.5:14b` + temperature 0.4→0.2. qwen3:14b 는 thinking 토큰이 max_tokens 잡아먹어 mid-output truncate (raw 1218자, POINT 2 부터 single-quote/nested 깨짐). qwen2.5:14b 로 안정 확인.
- **ULTRA lenient JSON 파서** (`qoo10_jp_detail.py`): 4단계 — 엄격 → smart-quote/trailing-comma fix → incremental } trim → raw 저장 (`backend/logs/llm_failures/`).
- **URL→SEO 재생성 통합** (DDDD-1, HHHH-1): `POST /api/products/regenerate-content-from-url` background task — Naver fetch v2 + OCR + SEO + JP detail + 진행률 폴링.
- **naver_fetch_v2** (Playwright): 1순위 CDP 9222 attach, 2순위 persistent context (`data/naver-browser-profile`).
- **Chrome 147 보안 차단 발견**: 메인 Default 프로필 + `--remote-debugging-port` → Chrome가 플래그 silent 무시 (CVE 보안 패치). 별도 user-data-dir 필수. → 메인 Chrome 에 탭 추가 안 됨, naver-browser-profile 별도 dir 영구 사용 확정.
- **사장님 Naver 1회 로그인**: `automation/open_naver_login_chrome.bat` → naver-browser-profile 로 Chrome 띄움 → 로그인 ("로그인 유지" 체크) → 닫기 → 영구 쿠키. headless 자동화가 같은 dir 재사용.
- **SheetRowDetailPanel**: URL 재생성 + Naver 로그인 setup 버튼 + JP detail UI 항상 표시 + 진행률 %.
- **SEO marketing_points** (`qoo10_content.txt`): qoo10-jp-detail-master 가이드 적용 (의태어, 약사법 회피, 패턴 A/B/C/D 분산).
- **자동 매칭 학습**: `auto_learning.py` + `match_quality.py` + `match_retry.py` (HHH-1 alt keyword). FFF-2 user_corrections 테이블.

## ─── 4/30 야간 자동화 상태 ────

- 4/30 00:30 자동화: STEP 3 트렌드 수집 0건 fail (큐텐 측 일시 장애 추정 — 12개 카테고리 모두 즉시 0건. 같은 endpoint 후일 수동 호출 시 정상 670개 수집됨 → 시스템 자체 문제 아님).
- 4/30 15:41 수동 재시작 (`python automation/daily_workflow.py`, PID 37168): STEP 3 스킵 (670개 이미 존재) → STEP 3.5 LLM 분류 421/0 완료 (16분) → STEP 4 자동 필터 진행. 채팅 종료 시점에 STEP 5+ (한국 매칭+이미지 다운로드, image/2026-04-30/ 폴더 생성 예정) 도달 안 함.
- 결과 확인: `logs/automation_20260430.log` tail + `image/2026-04-30/` 폴더 dir 생성 여부.

## ─── 4/28 새 작업 (commit 5건) ────

- `ad40788` R-3 daily_workflow STEP 5.7~5.95 통합 + Brand.aliases JSON + 검수 accepted 토글
- `df73a59` BB-1 옵션 selector + dropdown 트리거 + 가격 폴백
- `9a61810` CC-1 배송비 selector dt/dd + body fallback + parser 7/7 통과
- `2ca3b64` M-3 set_count cover OCR 폴백 (regex miss → image OCR → 정규식 재시도 → LLM with OCR)
- `bd31674` STATUS.md + .env.example 갱신

## ─── 알려진 이슈 / 대응 ──

- **백엔드 reload X**: PowerShell `Get-NetTCPConnection -LocalPort 8000 -State Listen | %{Stop-Process -Id $_.OwningProcess -Force}` + start.pyw
- **Chrome 147+ 메인 Default 프로필 9222 차단**: CVE 보안 패치로 `--remote-debugging-port` 무시. CDP attach 는 별도 user-data-dir 만 가능 (data/naver-browser-profile 등).
- **Naver 세션 만료 ≠ 쿠키 만료**: 쿠키 persistent + 미만료여도 Naver 가 IP/UA 의심 시 재인증 redirect 요구할 수 있음. 디스크 검사 (`naver_session_check`) 는 false negative 가능 — 야간 자동화 첫 fetch redirect 감지 시 즉시 알림 (TODO).
- **MEMORY 저장 위치**: `backend/logs/llm_failures/` (LLM JSON 파싱 실패 raw 덤프), `logs/automation_YYYYMMDD.log` (야간 자동화), `logs/llm_calls/YYYY-MM-DD.jsonl` (LLM 호출 누적)
- **Windows asyncpg + SSL traceback**: `_sync.run_sync()` SelectorEventLoop + engine.dispose
- **CMD cp949**: trigger 스크립트 `sys.stdout.reconfigure(encoding="utf-8")`
- **ollama supports_vision**: 모델 이름에 `vl/vision/llava/minicpm-v/moondream/gemma3` 키워드 — 새 비전 모델 추가 시 `ollama_client.py` 키워드 list 확장
- **minicpm-v 한국 화장품 약점**: 메디큐브/투에이엔 점수 0 빈도 — 향후 qwen2.5-vl 시도

## ─── 다음 작업 (잔여) ──

1. ★ 백엔드 재시작 후 4/28 옵션/배송 효과 검증 (`trigger_domestic_details --scrape --reset`)
2. ★ 내일 03:00 야간 자동화 실가동 검증 (R-3 흐름) — 텔레그램 알림으로 결과
3. 사장님 검수 별도 페이지 (현재는 토글만 — 명세 확정 시)
4. minicpm-v → qwen2.5-vl 교체 시도 (한국 화장품 인식 개선)
5. 폴더 다중 저장 (cover.jpg overwrite 방지)
6. `google-genai` 마이그레이션 (deprecated 경고 제거)

## ─── 참고 ──

- kc-cert-checker (`C:\Users\Admin\kc-cert-checker`) 패턴 적용: 헤드풀 + 검색→클릭 + OCR 폴백 + CDP attach
- 사장님이 디버그 Chrome 한 번 띄우고 네이버/쿠팡 로그인 → 자동화 활용
- 차단 시 사장님이 GUI 직접 풀면 자동화 계속
