---
name: feedback_always_commit
description: 작업 변경 후 항상 자동 커밋 (요청 없이도)
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e1b20f16-d8fb-401d-b867-033623a47421
---

2026-06-03. 사장님: "항상 커밋해". 코드/파일 변경 작업이 끝나면 별도 요청 없이도 항상 git commit 한다.

**Why:** 사장님이 매번 커밋을 지시하지 않아도 변경 이력이 남길 원함.

**How to apply:** 의미 있는 작업 단위가 끝날 때마다 커밋. 기본 브랜치(master)에서 직접 커밋 OK. push 는 별도 지시 시에만 — push 직후엔 short SHA 명시 ([[feedback_deploy_commit_notify]]). `frontend/dist` 는 gitignore 대상이라 add 하지 말 것.
