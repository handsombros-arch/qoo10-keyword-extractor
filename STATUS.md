# Qoo10 키워드 추출기 — 현재 상황 (2026-04-27)

VBA → Python(FastAPI) + React 재구축. 두 PC(메인 + Tailscale 노트북) 같은 Supabase 공유.
실행: `start.pyw` 더블클릭 → `localhost:8000` (CMD 없음, --reload 없음).

## 7단계 자동화 파이프라인 (사장님 큰 그림)

```
1.   키워드 추출 스케쥴링                    [부분 — daily_workflow 있음, 자동 트리거 X]
2.   임계점 자동 필터                        [완료 — /api/keywords/auto-filter]
3-1. 큐텐 → 스마트/쿠팡 매칭 (번역+이미지)    [Phase 1 — 코드 완료, 시운전 대기]
3-2. 브랜드 키워드 확장 (상위 10개 토큰 재검색) [Phase 1 — 대기]
4.   옵션별 가격 (한국 상위 10개 상세 진입)    [Phase 2]
4-1. 옵션별 원가                             [Phase 2]
4-2. 배송비 (무료/유료/조건부 파싱)            [Phase 2 — 컬럼 있음, 분석 X]
5.   누끼 + 식품/화장품 내용물 이미지         [Phase 2]
6.   상품시트 통합 + 실시간 재계산             [Phase 3 — 프론트 비중 큼]
7.   OCR + 큐텐 fit 상품명/옵션명/태그        [Phase 4]
```

매칭은 1차 cover 1:1 (현재) → 정확도 부족 시 2차 임베딩(CLIP 등).
옵션 스크래핑은 한국 상품 상위 10개 한정.

## Phase 1 (코드 완료, 시운전 대기)

**1-A 큐텐 상품명 jp→ko 번역** ✅ 코드
- `backend/app/services/llm/translate.py` `translate_jp_to_ko_async` (LLM + DB 캐시)
- 프롬프트: `prompts/jp_ko_translation.txt`
- 엔드포인트: `POST /api/products/qoo10/translate-names`
- 트리거: `automation/trigger_translate.py`
- 동작: 같은 product_name 1회만 LLM, `translation_cache` PK 중복 방지로 다음 날 재사용

**1-C 큐텐↔한국 cover 1:1 비전 매칭** ✅ 코드
- `backend/app/services/llm/image_match.py` `compare_two_images_async` (두 이미지 동시 입력 → 0~1 score+사유)
- 프롬프트: `prompts/image_matching.txt`
- 엔드포인트: `POST /api/recommendations/match-images`
- 트리거: `automation/trigger_match_images.py`
- 큐텐 1개당 한국 후보 top N (기본 3, image_score_overall DESC + price_krw ASC)
- (qoo10_id, domestic_id) 중복 비교 방지 → 결과는 `domestic_match_candidates` (decision: accepted/rejected)

**1-B 번역된 ko 로 한국 상품 재검색** ⏳ 대기 (1-A 결과 의존)
**1-D 브랜드 확장 (상위 10개 상품명 토큰 재검색)** ⏳ 대기

## 작업 A: 마진 200%+ 큐텐 묶음 set_count 비전 검증 (코드 완료, 시운전 대기)

- 엔드포인트: `POST /api/products/qoo10/verify-set-counts`
- 트리거: `automation/trigger_verify_set_count.py`
- 큐텐 단가 vs 한국 최저가 → 마진율 ≥200% 만 비전 호출 → `set_count_vision`/`_confidence`/`_verified_at` 업데이트
- 비전 호출 흔적 0건 (logs/llm_calls/2026-04-27.jsonl)

## 최근 커밋

```
895fadb feat: AI 4영역 인프라 + 자동화 트리거 + Phase 1 번역/이미지매칭
```
- 61 files changed, +6173 / -214
- 신규 모듈/엔드포인트/DB 모두 포함

## 노트북 셋업 체크리스트

```
1) git pull origin master
2) backend/.env 에 LLM 모델 + 임계값 추가 (.env.example 참조):
   TRANSLATE_MODEL=ollama:qwen3:14b
   TRANSLATE_FALLBACK_MODELS=ollama:qwen2.5:14b,ollama:qwen2.5:7b
   IMAGE_MATCH_MODEL=ollama:minicpm-v:8b
   IMAGE_MATCH_THRESHOLD=0.7
   TEXT_MATCH_THRESHOLD=0.10
   QOO10_CONTENT_MODEL=ollama:qwen3:14b
   BRAND_AUTO_ADD_THRESHOLD=0.85
3) ollama pull qwen3:14b qwen2.5:14b qwen2.5:7b minicpm-v:8b
4) start.pyw 더블클릭 → 자동 마이그레이션이 신규 컬럼/테이블 생성
```

## 한국 셀러 페이지 차단 우회 — 사용자 Chrome attach (Phase 2.5 권장)

쿠팡 vp/products / 스마트스토어 captcha 같은 봇 차단 우회 — 사용자가 띄운 디버그 Chrome 에 백엔드가 attach.

### 한 번 셋업
```
automation\launch_chrome_debug.bat 더블클릭
```

- 별도 프로필 (`%USERPROFILE%\qoo10-chrome-debug-profile`) 이라 평소 Chrome 안 닫아도 OK
- 디버그 Chrome 창 뜨면 네이버/쿠팡 등 한 번 로그인 → 다음부터 쿠키 누적
- 자동화가 차단(번호 입력 captcha)되면 그 창에서 직접 풀어주세요 — 자동화 계속

### 동작 흐름
- `m_domestic_details.py` 가 9222 포트 connect_over_cdp 우선 시도
- 사용자 Chrome attach 성공 시 → 그 ctx 의 새 탭으로 진입 (봇 탐지 거의 0)
- attach 실패 시 → browser_manager (큐텐 헤드풀) 의 ctx fallback

### 검증
```
curl http://localhost:9222/json/version
```
응답 있으면 attach 가능 상태.

## 야간 자동화 — Windows 작업 스케줄러 등록 (Phase 5)

매일 새벽 3시 자동 실행 등록 (사장님 PC 에서 한 번만):

```powershell
# 일반 PowerShell 창 (관리자 X 가능)
cd C:\Users\Admin\qoo10-keyword-extractor\automation
powershell -ExecutionPolicy Bypass -File .\setup_scheduler.ps1 -Time "03:00"

# 다른 시간 / 덮어쓰기
powershell -ExecutionPolicy Bypass -File .\setup_scheduler.ps1 -Time "19:00" -Force

# 수동 테스트 (즉시 실행)
Start-ScheduledTask -TaskName 'Qoo10DailyWorkflow'

# 상태 / 마지막 실행 시간
Get-ScheduledTask -TaskName 'Qoo10DailyWorkflow' | Get-ScheduledTaskInfo

# 제거
Unregister-ScheduledTask -TaskName 'Qoo10DailyWorkflow' -Confirm:$false
```

자동화 흐름 (`daily_workflow.py`):
- STEP 1~7 매일 자동 — 키워드 수집 → 분류 → 한국 매칭 → set_count → 이미지 → 추천 빌드
- 텔레그램 알림 (시작/완료/실패) — `automation/notify.py` 가 처리
- 로그: `logs/automation_YYYYMMDD.log`

Claude Code 메모리(`~/.claude/projects/`)는 PC별 별도 — 동기화 필요 시 수동 카피.

## 시운전 명령 (메인 PC RTX 5080 권장)

```bash
# 1-A 번역 — 작은 limit 먼저
python automation/trigger_translate.py --limit 20

# 1-C 이미지 매칭 — 상위 3개 한정 + 30쌍만
python automation/trigger_match_images.py --top 3 --limit 30

# A 작업 set_count 비전 검증 — 상위 5건만
python automation/trigger_verify_set_count.py --limit 5
```

## 핵심 모듈/DB 위치

**LLM 인프라** (`backend/app/services/llm/`)
- `category.py` 카테고리 분류 (6분류 + 기타)
- `brand.py` 브랜드 판별 + 자동 추가 (DB whitelist + LLM)
- `set_count.py` 묶음 개수 추출 (정규식 + LLM)
- `vision.py` 이미지 점수 + 패키지 카운트
- `translate.py` 일본어 → 한국어 번역 ★ 신규
- `image_match.py` 두 이미지 1:1 비교 ★ 신규

**모델 라우팅** (`.env` `<DOMAIN>_MODEL=provider:model`)
```
CATEGORY_MODEL=ollama:qwen2.5:14b
BRAND_MODEL=ollama:qwen2.5:14b
SET_COUNT_MODEL=ollama:qwen2.5:7b
VISION_MODEL=ollama:minicpm-v:8b
TRANSLATE_MODEL=ollama:qwen2.5:7b           ★ 신규
IMAGE_MATCH_MODEL=ollama:minicpm-v:8b       ★ 신규
IMAGE_MATCH_THRESHOLD=0.7                   ★ 신규
```

**DB (Supabase Postgres)** — 자동 마이그레이션 (`main.py _migrate_add_columns`)
- `keywords` + `category_inferred`, `is_brand`, `brand_kr/jp/en`
- `qoo10_products` + `set_count`, `set_count_source`, `set_count_vision`, `set_count_vision_confidence`, `set_count_verified_at`, `product_name_ko` ★
- `domestic_products` + `image_local_path`, `image_score_overall`, `image_score_json`
- `brands` (신규 — 시드 50 + 자동 추가 24)
- `translation_cache` (신규 — PK source_text+source_lang+target_lang) ★
- `domestic_match_candidates` (신규 — qoo10_id, domestic_id, image_score, decision) ★

## daily_workflow.py 통합 STEP

```
STEP 1   헬스체크
STEP 2   로그인 상태
STEP 3   트렌드 키워드 수집 (M02)
STEP 3.5 LLM 카테고리+브랜드 분류    ENABLE_LLM_CATEGORY=1
STEP 4   자동 필터 (categories 화이트리스트)
STEP 5   한국 상품 수집 (쿠팡+네이버+큐텐)
STEP 5.5 큐텐 set_count 추출         ENABLE_SET_COUNT_EXTRACTION=1
STEP 5.7 한국 이미지 다운+비전+폴더링 ENABLE_DOMESTIC_IMAGES=1
STEP 6   추천 자동 빌드 (마진 — set_count 단가 환산)
```

## 검증된 시간 (4/25 큐텐 1086장 / 425 unique)

- 카테고리+브랜드 분류 425 unique: ~9분 (qwen2.5:14b)
- set_count 추출 688 unique: ~4분 (정규식+LLM)
- 이미지 처리 1086장: ~37분 (minicpm-v:8b 1.7초/장)

## 알려진 이슈

- **Windows asyncpg + SSL traceback**: `_sync.run_sync()` SelectorEventLoop + engine.dispose
- **CMD cp949**: trigger 스크립트 stdout 시작 시 `sys.stdout.reconfigure(encoding="utf-8")`
- **백엔드 모듈 reload X**: 코드 변경 후 PowerShell `Stop-Process python,pythonw + start.pyw` 재시작 필수
- **ollama 비전 매칭**: 모델 이름에 `vl/vision/llava/minicpm-v/moondream/gemma3` 키워드 필수 — 새 비전 모델 추가 시 `ollama_client.py` 키워드 list 확장
- **minicpm-v 한국 화장품 인식 약점**: 메디큐브/투에이엔 등 점수 0 빈도 — 향후 qwen2.5-vl 시도 또는 prompt 보완

## 우선순위 (다음 작업)

1. Phase 1 시운전 (translate-names + match-images 작은 limit)
2. 결과 보고 임계값/프롬프트 튜닝 → 정확도 부족 시 CLIP 임베딩 도입
3. 1-B (번역된 ko 로 한국 상품 재검색)
4. 1-D (브랜드 키워드 상위 10개 토큰 재검색)
5. Phase 2 진입 (옵션별 가격/원가 + 배송비 파싱 + 누끼/내용물 이미지)

## 미적용 / 미구현

- 한국 상품 set_count 추출 (현재 큐텐만)
- 비전 평가 → 시트 UI 표시 (image_score_overall 정렬/필터)
- 새 SDK `google-genai` 마이그레이션
- 폴더 다중 저장 (cover.jpg overwrite 방지 — 같은 product_name 여러 행)
