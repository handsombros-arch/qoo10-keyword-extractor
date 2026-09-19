---
name: Qoo10 — 장시간 작업 시 실시간 진행률 보고
description: 5분 이상 걸리는 작업은 백그라운드 + Monitor 로 60-90초 주기 진행률 보고. 사용자가 명시적으로 요청.
type: feedback
originSessionId: 6eae401a-649d-4d42-b7b9-99a01e9035f0
---
**5분 이상 걸리는 백그라운드 작업은 Monitor 도구로 진행률 알림 보내기.**

**Why:** 사용자가 명시 — "진행률도 보여줘". 425 키워드 분류 (~9분), 1086장 이미지 처리 (~37분) 같은 장시간 작업에서 진행률을 실시간으로 보면 안심. 침묵하면 막연.

**How to apply:**
- 5분 이상 예상되면 `Bash run_in_background` + `Monitor` (60-90초 주기) 패턴
- Monitor 의 polling python 스크립트는 DB 카운트 직접 쿼리 (backend task_manager 폴링도 OK 지만 backend 재시작 시 task 사라짐 → DB 가 신뢰성)
- 진행률 출력 형식: `[HH:MM:SS] [██████····] N/total (NN%)  [추가 metric]`
- 100% 도달 시 `sys.exit(42)` 같이 명시적 종료 코드로 monitor 자체 종료
- 단발 응답: 한 줄 "% — 약 N분 더" 정도 짧게
