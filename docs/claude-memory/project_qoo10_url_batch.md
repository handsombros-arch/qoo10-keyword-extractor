---
name: Qoo10 야간 URL 일괄 처리 (A+B+C+D, 2026-05-03)
description: 시트 URL 입력 → 새벽 자동 처리. Naver/Coupang 모두 메인 Chrome 확장 경유. 큐 영속화 + TTL.
type: project
originSessionId: 636ff6c7-00a5-455c-8bf9-191cc2a4997b
---
**2026-05-03 구축.** 사장님 요청: "내가 URL을 넣으면 네,쿠 모두 자동으로 밤에 돌아갈 수 있게". PC + 메인 Chrome 켜져있다는 가정 (PC OFF 케이스는 추후 별건).

## 5-step (모두 완료)

### A. URL 라우터 — `_do_regenerate` 분기
- `backend/app/api/products.py` `_do_regenerate` 가 URL 도메인별 자동 분기
- 새 kwarg `product_name_hint` 도입 (D 이후에는 사용 안 됨, 호환성용 유지)
- 시트 [URL 재생성] 버튼이 Naver + Coupang 둘 다 받음 (`SheetRowDetailPanel.tsx`)

### B. 확장 큐 SQLite 영속화 + TTL/stale
- `backend/app/api/extension.py` 의 `_jobs` 메모리 → `data/ext_queue.db` write-through 영속화
- 백엔드 startup 시 큐 복원: `initialize_queue()` (in_progress → PENDING 으로 되돌림 = 재처리)
- `cleanup_stale_jobs_loop()` 1분 주기: in_progress > 10분 → FAILED, completed/failed > 1시간 → purge
- `main.py` lifespan 에 wiring

### C. 야간 URL batch job — STEP 4.7
- `backend/app/api/automation.py` `POST /api/automation/url-batch-regenerate`
- 시트 스캔 → "URL 있고 데이터 미수집" 행 추출 → 각 행 `_do_regenerate` 호출
- 부분 저장 (행마다 시트 UPDATE — 오류 시 진행분 보존)
- `automation/daily_workflow.py` STEP 4.7 추가 — keyword_only / full 둘 다에서 동작
- env: `ENABLE_URL_BATCH_REGENERATE=1` (기본 ON), `URL_BATCH_LIMIT=30`

### D. Coupang 도 메인 Chrome 확장 경유 (5/3 추가, AKAMAI 우회)
**Why:** A 단계는 백엔드 Scrapling 사용 → 실측 시 AKAMAI 가 짧은 시간 반복 호출에 차단. 사장님 메인 Chrome (확장 설치된 곳) 은 평소 trust 누적 → AKAMAI 통과.

**구현:**
- 확장 manifest.json `version: 0.2.0` + `host_permissions` 에 `coupang.com/*` 3개 추가
- 확장 `background.js` 에 `detectSite(url)` + site-aware dispatch (naver = page world dump + naver-smartstore.js, coupang = DOM-only + coupang.js)
- 확장 `content-scripts/coupang.js` 신규: DOM 셀렉터 추출 + 휴리스틱 필터
  - **review 차단 정규식**: `/(별점|평점|리뷰|후기|평가|만족도|등급|stars?|rating|review|score|총점|모든\s*별점|좋음|좋아요|보통|별로|나쁨|최고|최악)/i`
    - **Coupang 리뷰 분포 라벨**: "모든 별점 / 최고 / 좋음 / 보통 / 별로 / 나쁨" (5단계). "좋아요" 가 아니라 **"좋음"** 임 (5/3 검증). 헷갈리지 말 것.
  - cover image: 큰 이미지 (300x300+) JS evaluate + `_next/static/`, `front-web-next` 정적자원 제외
  - options 셀렉터: `[class*='Option'] li` 같은 너무 느슨한 건 제거. ZWSP/NBSP 보이지 않는 문자 strip 필요 (regex source 에는 `​` 같은 escape 사용. 리터럴 invisible char 넣으면 JS 파싱 깨짐)
- 백엔드 `_do_regenerate`: Coupang URL 도 `ext_client.fetch_one` 경유 (Naver 와 동일 path)
- `ext_client.py` `_to_naver_fetch_schema` 에 `_ext_debug` / `_ext_version` 패스스루

**검증 (5/3 그랑누보 백팩 URL):**
- ELAPSED 42.6s
- AKAMAI 통과 ✓
- product_name / cover / price 25590 / shipping 무료배송 / 옵션 6/6 review 차단 ✓
- SEO LLM (qwen2.5:14b) title 121자 / tags 6 / marketing 4 ✓

### F. JP 상세 프롬프트 카테고리별 분기 (5/3 추가)
**Why:** 프롬프트 출력 JSON 예시에 화장품 단어 (毛穴/ハリ肌/整肌成分) 박혀있어 백팩 같은 비-화장품 상품에서도 LLM 이 그대로 복사 (예: 백팩 carry pain point 가 "毛穴が気になる" 로 나옴).

**구현:**
- `backend/app/services/llm/prompts/qoo10_jp_detail.txt` 의 cosmetic 예시 → `<카테고리 적합 ...>` placeholder
- `qoo10_jp_detail.py` 에 `_category_guidance(category)` 헬퍼 추가 — 5종 가이던스 (뷰티/패션/식품/가전/생활) + GENERIC fallback
- 프롬프트 상단에 카테고리 적합 단어 + 절대 금지 단어 명시
- `_do_regenerate` 가 `category_hint` (사장님 시트) → `info.category_path` (페이지) → "기타" 우선순위로 resolve
- 프론트엔드: body 에 `category: edit.category` 전달

### G. 카테고리 자동 분류 (5/3 추가)
**Why:** 사장님이 직접 URL 추가한 행은 `keyword_jp` 없어 R-7 자동 매핑 불가. 시트 카테고리 비어있으면 JP detail 의 `_GUIDANCE_GENERIC` 가 적용되어 카테고리별 톤 효과 못 봄.

**구현:**
- `_do_regenerate` 가 category_hint + page category_path 모두 빈 칸이면 → `classify_category_async(name)` (R-7 STEP 3.5 와 동일 LLM 6분류) 호출
- 6분류 결과: 03.뷰티&화장품 / 06.홈&생활 / 07.식품 / 09.베이비&키즈 / 12.서플리먼트&다이어트 / 기타
- 응답에 `category` 필드 + `_source.category_auto_classified=true` 추가
- 프론트엔드: `result.category && !edit.category` 일 때만 시트 row.category 자동 채움 (사장님 수동 입력 보호)

### E. [URL 재생성] 이미지 다운로드 + 폴더링 (5/3 추가)
**Why:** 사장님 요청. 시트의 cover URL 만으론 부족, 디스크에도 보존 + 상세 내용물 이미지도 함께.

**구현:**
- `_do_regenerate` 에 다운로드 단계 추가 (SEO 직후, JP detail 직전)
- 저장 위치: `image/{today_iso}/{_safe_folder_name(name)}/{cover.jpg, detail_1.jpg, detail_2.jpg}`
- 다운로드 대상: cover 1장 + extra_image_urls 중 cover 와 다른 첫 2장 (de-dup)
- `_download_image_to_path()` — httpx fetch → PIL JPEG 변환 → 저장 (best-effort, 실패해도 다른 단계 계속)
- 응답에 `cover_local_path`, `detail_local_paths`, `image_folder` 필드 추가
- 프론트엔드 `SheetRowDetailPanel.tsx`: 시트 row 에 위 필드 저장 + 메시지에 "이미지 N장 저장" 표시
- `productSheet.ts` SheetRow 타입에 위 3 필드 추가
- 정적 서빙: `/image` route 가 IMAGE_ROOT 그대로 노출 (이미 `main.py` 에 mount 됨) — 브라우저에서 `http://localhost:8000/image/...` 로 표시 가능

**검증 (5/3 그랑누보 백팩):**
- 62.7s
- 3개 파일 (cover 27.3KB, detail_1 11.7KB, detail_2 11.1KB) 모두 다른 MD5
- 폴더 `image/2026-05-03/그랑누보_데일리_초경량_여자_백팩_가방/`

## 별건 발견 (5/3)

### qwen3:14b thinking truncate → qoo10_content 도 qwen2.5:14b 로 분리
- `.env`: `QOO10_CONTENT_MODEL=ollama:qwen3:14b` → **`qwen2.5:14b`** 로 변경
- 4/30 에 JP detail 만 분리됐는데 qoo10_content 에도 동일 이슈 있어 같이 분리
- 증상: LLM 호출 시 빈 응답 (thinking 토큰이 max_tokens 잡아먹어 mid-output empty)
- Naver 와 Coupang 모두 영향 (SEO 흐름 공통)

## 흐름 (야간)

```
00:30 야간 자동화
  STEP 1~4.5 (키워드 RD)
  STEP 4.7 URL 일괄 재생성
    └→ POST /api/automation/url-batch-regenerate
       └→ 시트 N개 행 (limit=30)
          └→ 모두 ext_client.fetch_one (Naver=naver-smartstore.js, Coupang=coupang.js)
             └→ 메인 Chrome 확장이 1분 alarm 폴링 → 처리
       └→ 각 행 처리 후 시트 부분 저장
  STEP 5+ (full mode 일 때만)
```

## 전제

- **PC 켜져 있어야** — 새벽 OFF 면 둘 다 못 함 (별건)
- **메인 Chrome 열려 있어야** — Naver/Coupang 모두 확장 경유
- **확장 SW 살아있어야** — B 의 stale detection 으로 보강

## 알려진 한계 / 향후

- alarm 1분 주기라 backend enqueue 후 평균 30초 대기 (popup [즉시 폴링] 으로 단축 가능)
- coupang.js DOM 셀렉터는 Coupang UI 변경 시 깨질 수 있음 — `_ext_debug.opts_raw` 가 응답에 포함돼 있어 디버깅 가능
- `DEBUG_COUPANG_DUMP=1` env 설정 시 `logs/diag_coupang/<ts>/{page.html,screenshot.png,summary.txt}` 자동 저장 (백엔드 Scrapling 경유 시만 동작 — 확장 경유 시는 미동작. 옛 코드 잔존)
- `_fetch_coupang_via_browser_manager` 와 backend Scrapling 경로는 nightly automation `scrape_domestic_detail` 에서 여전히 사용 (full mode). [URL 재생성] 흐름에서만 확장 경유로 변경.
