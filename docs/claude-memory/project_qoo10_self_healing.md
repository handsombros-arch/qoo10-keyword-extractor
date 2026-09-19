---
name: Qoo10 자가 진단/수정 시스템 (R-4)
description: 5/1 자동화 hang 사고 후 구축한 자동 검증 + 회복 시스템. run_nightly + verify_run + recover.py + watchdog 4종.
type: project
originSessionId: 503abfe6-0640-4332-96c5-095d3e4e6208
---
**2026-05-01 구축.** 4/29-5/1 야간 자동화 연속 실패 (3일 연속 hang) 후 사장님 요청으로 추가.

## 4종 도구 (`automation/` 추가)

| 파일 | 역할 |
|---|---|
| `daily_workflow.py` | 본 워크플로우 (수정: watchdog + STEP 4 0개 진단) |
| `recover.py` | 누락 단계 재실행 CLI (STEP 6.0/6/6.6/6.7/6.5/7 idempotent) |
| `verify_run.py` | 산출물 6개 검증 (DB+API+파일) → 누락 STEP 리스트 출력 |
| `run_nightly.py` | Task Scheduler 진입점 — workflow + verify(--recover) + morning_report 통합 |

## 흐름

```
Task Scheduler @ 03:00
  └─→ run_nightly.py {today}
       ├─→ daily_workflow.py    1차 시도 (rc≠0,2,3 면 60초 후 1회 재시도)
       │    └─ wait_task watchdog: 5회 폴링 실패 → /api/auth/status →
       │                            죽음 → 8000 포트 kill + start.pyw 재실행 + 30초 대기
       │    └─ with_retry watchdog: ConnectError 시 동일 procedure
       │    └─ STEP 4 = 0 시 _diagnose_filter_zero (loose threshold 비교)
       ├─→ verify_run.py {date} --recover
       │    └─ C1~C6 검증 → 누락 → recover.py --only X,Y,Z 자동 호출 → 재검증
       └─→ morning_report.py    텔레그램 요약
```

## verify_run 점검 항목 (`STEP_FOR_CHECK` 매핑)

| ID | 점검 | 회복 STEP |
|---|---|---|
| C1 | `/api/keywords/dates` 에 target_date count > 0 | 3 |
| C2 | auto-filter idempotent 호출 → 1개 이상 통과 | 3 |
| C3 | `/api/review/{date}` candidates ≥ 1 | 6 |
| C4 | `image/{date}/` 폴더 ≥ expected_n × 70% | 6.7 |
| C5 | review payload qoo10_title_jp 채워진 비율 ≥ 50% | 6.0 |
| C6 | set_count 검증 표시 (info-only) | 6.5 |

## recover.py 사용

```bash
python automation/recover.py 2026-05-01           # 자동 감지 + 누락 STEP 실행
python automation/recover.py 2026-05-01 --only 6,6.7   # 특정 STEP만 (image 폴더 빠른 복구)
python automation/recover.py 2026-05-01 --from-step 6  # 6 부터 끝까지
python automation/recover.py 2026-05-01 --dry-run      # POST 모킹
```

## 새 setup_scheduler.ps1 옵션

```ps1
.\setup_scheduler.ps1 -Time "03:00"                           # run_nightly 사용 (기본)
.\setup_scheduler.ps1 -Time "03:00" -UseLegacyWorkflow         # daily_workflow 직접 (롤백)
```

## watchdog 동작 (1단계)

`daily_workflow.py` 의 `wait_task` + `with_retry` 가 다음 자동 처리:
1. 백엔드 ping (`/api/auth/status` 5초 timeout) 으로 alive 판정
2. 죽었으면 `Get-NetTCPConnection -LocalPort 8000` kill + `start.pyw` 재실행
3. 30초 안에 alive 면 재진행, 실패면 `StepFailed` raise → outer 가 verify+recover 로 보충

**한계:** task_id 는 in-memory 라 백엔드 재시작 시 유실. 그래서 outer wrapper (`run_nightly`) 가 verify+recover 로 누락 보충하는 구조.

## STEP 4 = 0 진단 (2단계)

`_diagnose_filter_zero` — 같은 endpoint 를 loose 임계값 (vol=0, kr=0, comp=999) 로 재호출:
- loose 도 0 → 메타데이터 누락 (search_volume null) → STEP 3 재수집 권고
- loose 만 양수 → 임계값 과다 → settings 점검 권고

4/30 사례 (00:30 큐텐 0건 → 670 수동 보충 → STEP 4 0개) 가 트리거.

## 5/1 사고 회복 결과

- **5/1 03:00 자동화**: STEP 5.95 match-images 완료 직후 daily_workflow 프로세스 silent kill (아마 OS sleep). 백엔드는 alive.
- **수동 회복**: `recover.py 2026-05-01 --only 6,6.6,6.7` → 14 candidates auto-build, image/2026-05-01/ 14 폴더 생성. STEP 6.6 retry 가 ollama 경합으로 8분+ hang → STEP 6.7 직접 호출로 우회.
- **4/30 회복**: 그날은 STEP 3 큐텐 0건 + 수동 보충된 670개에 메타 부족으로 STEP 4 0개. 5/1 시점 메타 보강 후 STEP 4 = 45개 통과 → recover 6,6.7 → image/2026-04-30/ 15 폴더 생성.

## 알려진 한계 / 향후 개선

1. **task_manager DB 영구화** — backend 재시작 시 진행 중 task 잃음. 현재는 verify+recover 가 보충하지만 STEP 5.95 (match-images, 1~2시간) 같은 비싼 단계는 loss 큼.
2. **STEP 6.6 retry 동시성** — STEP 6.0 가 ollama 점유 시 retry 가 한 키워드에서 hang. 직렬 실행이 안전. 또는 retry timeout 추가.
3. **OS sleep 방지** — 5/1 사고처럼 daily_workflow 프로세스가 OS sleep 으로 죽으면 watchdog 무용. Task Scheduler "Wake the computer to run this task" 옵션 활성화 필요.

## R-7 (2026-05-01) — 시트에 등록 상태 토글

**Why:** "상품 시트 본래 목적 = 마진 계산 + 등록 전 최종 세팅 + 기록" — 158행 누적되며 흐려짐. 사장님 결정: 일단 등록중/등록완료 표기부터.

**구현:**
- `SheetRow.registration_status` 필드 추가 (`'미정' | 'in_progress' | 'completed'`).
- `SheetRow.registered_at` (ISO date), `qoo10_product_id` (선택 추후 매출 추적용).
- `migrateRow` default 미정. `newSheetRow` default 미정.
- RecommendProductsPage 좌측 pinned 컬럼 "등록상태" — agSelectCellEditor 드롭다운, 색깔 (회색/노랑/녹색).
- onCellValueChanged: completed 로 바뀌면 `registered_at = today`, completed 에서 다른 값으로 바뀌면 클리어.
- 상단 toolbar 등록상태 필터 (`전체` / `진행중 (완료 숨김)` / `미정` / `등록중` / `등록완료`). localStorage 저장 (`sheet.statusFilter`).

**파일:**
- `frontend/src/store/productSheet.ts` — type + migrate + newSheetRow
- `frontend/src/pages/RecommendProductsPage.tsx` — 컬럼 + 필터 UI + onCellValueChanged 자동기록

## R-6 (2026-05-01) — 자동화 범위 축소: 키워드 RD까지만

**Why:** 매칭/이미지/auto-build 흐름이 5/1 사고처럼 자주 hang/실패 → 사장님이 holds 결정. 시트는 본래 목적 (마진 계산 + 등록 전 최종 세팅 + 기록) 인데 자동화 잡다 데이터로 희석됨.

**새 흐름 (사장님 결정):**
- **자동화 (야간)**: 키워드 RD = STEP 1 (헬스체크) → 2 (로그인) → 3 (트렌드 수집) → 3.5 (분류) → 4 (필터) → 4.5 (M05 다양성) 까지만.
- **수동 (사장님)**: 국내쇼핑 검색, 상품 선정, 옵션, 원가 입력 — KeywordPage / 시트 직접.
- **유지 기능**: URL → 이미지 썸네일 + 폴더링 + 마케팅 포인트 (`POST /api/products/regenerate-content-from-url`). SheetRowDetailPanel 의 [URL 재생성] 버튼.

**구현:** `daily_workflow.py` 새 env `AUTOMATION_MODE`:
- `keyword_only` (기본) — STEP 4.5 후 즉시 종료
- `full` — 레거시 (STEP 5+ 포함)

`verify_run.py` 도 mode 인지 — keyword_only 면 C3+ (auto-build/폴더/SEO) 검증 스킵.

기존 STEP 5+ 코드는 살림 (full mode 유지) — 추후 부활 가능.

## R-5 (2026-05-01) — 키워드 다양성 개선

큐텐 트렌드 페이지 인기도 누적 → 매일 같은 670 키워드 → STEP 4 통과 33개 거의 고정. 사장님 5/1 체감 (4/30→5/1 jaccard 0.95). M05 활성화로 신규 발굴.

**추가 도구:**
- `automation/diagnose_keyword_freshness.py {--days N}` — 일자별 unique + 신규 + 인접 일자 jaccard 표 출력. 4/25~5/1 평균 jaccard 0.79, 일평균 신규 31건 (4/29-30 = 0.95 — 거의 동일).
- `GET /api/keywords/freshness?days=14` — 위 진단의 backend 데이터 소스.
- `POST /api/keywords/expand-related` — `keywords_jp[]` 받아 M05 RelatedKeywordScraper 호출 → 유사/연관 키워드 추출 → 번역 → `expanded_keywords` INSERT (parent_jp + keyword_jp UNIQUE dedup).
- `daily_workflow.py` STEP 4.5 (자동 필터 직후) — `step_collect_related_keywords` 33 후보에 M05. ENV `ENABLE_RELATED_KEYWORDS=1` (기본 ON), `RELATED_KEYWORDS_MAX_PER_PARENT=15`.
- `recover.py --only 4.5` 가능.

**효과 측정:** 5/2 야간 자동화 실가동 후 `python automation/diagnose_keyword_freshness.py --days 3` — `expanded_keywords` 일별 신규 INSERT ≥ 200건, 5/2 unique keywords ≥ 700 기대.
