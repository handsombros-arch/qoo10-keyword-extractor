---
name: Qoo10 GGG-2 cover_description 매칭 룰 분석 계획
description: 사장님이 "GGG-2 분석해" 트리거하면 실행할 작업 — 1주 누적 corrections + cover_description 으로 매칭 룰 제안
type: project
originSessionId: 9ff2774a-1471-4fe2-a0dc-6403f4b97371
---
GGG-1 (qwen2.5vl cover description) 완료 후속 작업. 2026-05-06 (수) 또는 그 이후 사장님이 "GGG-2 분석해" / "cover description 분석" 등으로 트리거 시 실행.

**Why:** GGG-1 직후 (2026-04-29) 데이터가 부족 (corrections 0건, descriptions 178건) — 1주 사장님이 시트로 swap/reject 작업 누적 + 매일 자동화로 새 description 쌓인 후 분석해야 의미 있음.

**How to apply:** 트리거 시:
1. backend 헬스체크 (curl http://localhost:8000/docs)
2. 통계 수집:
   - `SELECT decision_kind, count(*) FROM user_corrections GROUP BY decision_kind`
   - `SELECT count(*) FROM qoo10_products WHERE cover_description IS NOT NULL`
   - `SELECT count(*) FROM domestic_products WHERE cover_description IS NOT NULL`
   - swap 사례에서 AI choice cover_description vs user choice cover_description 비교 (자카드/공통 토큰)
3. 패턴 분석:
   - qwen2.5vl 자주 틀리는 카테고리 (예: D'Alba 화장품 → wine 오인)
   - cover_description 토큰이 매칭에 도움됐을 swap 케이스
   - 현 image_match 임계값 (text>=0.10 AND image>=0.7) 적정성
4. 출력 (마크다운 200줄 이내):
   - prompt 개선안 (cover_describe.py 의 _PROMPT)
   - 결합 룰 — cover_description 자카드 score 추가 (자카드 >= X → image 임계값 완화)
   - 임계값 조정 구체 숫자
5. 코드 변경은 사장님 승인 후.

데이터 부족 (corrections < 10건) 시 → 분석 보류 + 1주 더 기다리자고 제안.

**파일 참조:**
- `backend/app/services/llm/cover_describe.py` — qwen2.5vl prompt
- `backend/app/services/llm/image_match.py` — 결합 룰
- `backend/app/db/models.py` — UserCorrection / Qoo10Product / DomesticProduct
- `backend/app/api/automation.py` — `/api/sheet/correction` (POST), `/api/sheet/corrections` (GET)
