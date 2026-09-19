# AGENTS.md — 엘비텐(LV10) 작업 규칙

큐텐 재팬 셀러용 키워드 발굴·한국 소싱 마진 도구. FastAPI(`backend/`) + React(`frontend/`) + Supabase Postgres. 맥북이 매일 키워드/낙찰가 수집, 윈도우 메인 PC 에서 검수·마진 작업.

**작업 시작 전 반드시 읽기:** `docs/HANDOFF_2026-09-19.md` → `docs/claude-memory/README.md` (읽는 순서 안내) → `docs/claude-memory/project_lv10_reset.md`.

## 절대 규칙
1. `keywords` / `volume_history` / `bid_history` 등 누적 테이블에 DELETE·DROP·TRUNCATE 금지. 마이그레이션은 ADD COLUMN 만. `save_keywords` 의 안전가드(`KEYWORD_SAVE_GUARD_RATIO`) 우회·약화 금지. 저장·동기화는 union, 행수가 줄면 경고.
2. 유료 LLM API(Claude/OpenAI 등)·VPS 사용 금지. 로컬 ollama(메인 PC)·Papago 웹·무료 환율 API 만.
3. 백엔드 없는 UI 껍데기 만들지 말 것. 기능은 끝까지 동작하게.
4. 화면 버그는 재현 확인 후 수정. 확인 전 "고쳤다" 보고 금지.
5. 변경 후 항상 커밋(한국어 메시지, `feat/fix/chore(scope): 요약` 형식). 한글 포함 `.ps1` 은 UTF-8 BOM. `.sh`/`.plist` 는 LF.

## 실행
- 윈도우: `start.pyw` 더블클릭 → `http://localhost:8000` (`--reload` 없음 → 코드 수정 후 수동 재시작).
- 재시작: `Get-NetTCPConnection -LocalPort 8000 -State Listen | %{Stop-Process -Id $_.OwningProcess -Force}` 후 `start.pyw`.
- 프론트 변경 시 `cd frontend && npm run build` (백엔드가 dist 정적 서빙).
- 맥북: `automation/mac/` 참고. 일일 수집 = `python automation/trigger_daily_rd.py`.
- 백엔드/트리거 스크립트는 stdout UTF-8 강제 필요 (cp949 크래시 방지 — 이미 적용됨, 새 스크립트도 동일하게).

## 사용자
한국어. 기술 배경 깊지 않음 → 설명은 짧고 구체적으로, 명령은 복붙 가능한 블록으로. 장시간 작업은 60~90초 주기로 진행률 보고.
