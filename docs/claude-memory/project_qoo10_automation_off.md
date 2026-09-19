---
name: Qoo10 야간 자동화 OFF (2026-05-16~, 11시 알림도 5/21 폐지)
description: 2026-05-16 야간 자동화 3종 모두 Disabled. 5/21 11시 알림(Qoo10KeywordAlert)도 폐지 — 사장님 자율 수동 트리거.
type: project
originSessionId: fdcdd33c-3e59-48b1-bd11-6d21ab6ed2b6
---
**2026-05-16 결정.** 사장님: "자동화는 됐고, 오전 11시에 알럿으로 키워드 자동화 돌리라고 알려줘. 현재 자동으로 도는 것들 다 취소"

## Disabled Scheduled Tasks (3종)

```
Qoo10DailyWorkflow   Disabled  (구 03:00 / 최근 00:30 야간 자동화 — run_nightly.py)
Qoo10ChromeDebug     Disabled  (Chrome 9222 자동 launch)
Qoo10MorningReport   Disabled  (08:00 텔레그램 리포트)
```

Disable 만 함 (Delete 아님) — 사장님이 부활 결정 시 `Enable-ScheduledTask -TaskName <name>` 한 줄로 복구.

## ~~Qoo10KeywordAlert~~ (2026-05-21 폐지)

5/16~5/20 동안만 운영. 5/21 사장님이 "이거 알림 없애도 돼" 로 폐지 결정.
- `Unregister-ScheduledTask -TaskName Qoo10KeywordAlert` 완료
- `automation/alert_keyword_run.ps1` 삭제 완료
- 사유: 사장님이 알림 없이도 출근 후 수동 실행 흐름 자율적으로 가능 판단
- (참고) 5/20 커밋 1b85991 에서 스크립트 추가됐다가 5/21 삭제됨. BOM 누락으로 한글 깨짐 → BOM 추가 후 검증 → 결국 폐지 결정.

## 끈 이유

**STEP 4.7 (URL 일괄 재생성) 탬버린즈 무한 반복.**
- `backend/app/api/automation.py:1366-1392` `_needs_regen`: title_jp+cover+price 셋 다 채워져야 skip
- 시트 앞쪽 탬버린즈 URL 30건이 매번 실패 (5/12, 5/13 둘 다 0/30 success)
- 데이터 안 채워짐 → 다음 날 또 같은 30건 선택 → URL_BATCH_LIMIT=30 이라 나머지 시트는 영영 차례 못 옴
- 사장님이 자동화 자체 OFF 결정

## How to apply

- 이후 사장님이 "야간 자동화"를 다시 언급하면 **현재 OFF 상태** 임을 먼저 확인. Enable 필요.
- 야간 흐름(R-3, R-6, STEP 4.7) 관련 작업 제안 시 "현재 야간 OFF" 전제로 설명.
- 11시 알림 받고 사장님이 수동 실행하면 `start.pyw` 또는 `python automation/daily_workflow.py` 로 트리거됨.

## 2026-05-18 업데이트 — STEP 4.7 무한 반복 fix 완료

- `backend/app/api/automation.py` `_needs_regen()` 에 **backoff 로직 추가** — `_url_batch_fail_count`, `_url_batch_error_at` 기반. 실패 행은 1→2→4→7일 간격으로만 재시도. 성공 시 세 필드 모두 제거 (자동 회복).
- **그러나 자동화 재개는 보류** — 사장님 결정: Intel Mac 이전 끝난 뒤 hermes-agent cron 으로 한꺼번에 켜기. `[[project_qoo10_mac_migration]]` 참조.
- STEP 3 키워드 0건 (5/15·5/16) 도 같은 날 fix — `m02_trend_keywords.py` 에 page warmup + retry 추가.
- 따라서 현재 OFF 사유는 "코드 결함" → "맥북 이전 대기" 로 변경됨.
