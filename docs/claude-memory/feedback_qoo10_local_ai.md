---
name: Qoo10 프로젝트 — 비용 0 + LLM 호출 최소화 + Max 구독 활용
description: 2026-05-21 갱신. ollama 품질 부족 인지 후 방향 전환 — API 사용 안 함 (Claude/OpenAI 둘 다), LLM 호출 자체를 DB 영속화로 줄이고 잔여 호출만 ollama+Claude Code Max 분담.
type: feedback
originSessionId: 6eae401a-649d-4d42-b7b9-99a01e9035f0
---
**Qoo10 LLM 정책 (2026-05-21 갱신):**
- ❌ Claude API / OpenAI API / 어떤 유료 API 도 안 씀 (사장님 5/21 명시)
- ❌ ollama 만으로는 품질 부족 (사장님 5/21: 번역=brand 매핑/한국 검색 노출, OCR 한국 화장품 약점, 둘 다 만족 못함)
- ✅ Claude Max 구독 (Claude Code CLI) — quota 안에서 무료
- ✅ ChatGPT Plus (Codex CLI) — 옵션
- ✅ 로컬 ollama (메인 PC RTX 5080 16GB) — 호출 횟수 적을 때만 쓸 만함

**Why (5/21 사장님 인사이트):** ollama 품질 한계가 "번역" 의 본질을 못 잡음 — 사장님이 원하는 번역은 단순 jp→ko 가 아니라 brand 인지 + 한국 검색엔진 매칭 (예: "ダルバ ホワイトトリュフ" → "달바 화이트 트러플"). 14B 범용 모델은 한국 화장품 brand 학습 빈약. OCR (minicpm-v) 도 메디큐브/투에이엔 점수 0 사례 누적. 스크래핑은 별개 만성 문제.

**핵심 발상 전환:** "자동화 LLM 호출 2000~3000회/일" 가정 자체를 폐기. DB 영속화 + 캐싱 + brand alias 시드로 **일 10~50회로 축소**. 그러면 어떤 LLM 백엔드든 quota 안에 들어옴.

**How to apply:**

호출 횟수 감축 전략 (우선순위):
1. `translate` — `translation_cache` (이미 존재) + `brand_aliases` 적극 채움 → cache hit, 호출 0
2. `category` — keyword_jp → category 영속 캐시 추가 → 재키워드 호출 0
3. `brand_expand` — brand 단위로 1회만 → DB 영속, 이후 lookup
4. `set_count` — 정규식 + cover OCR 로 90% 잡고 폴백 미스만 사장님 수동 (5~10회/일)
5. `image_match` — (qoo10_id, domestic_id) 매칭 결과 캐시. 본질적 LLM 필요 부분만 잔존 (~200회/일 if 캐시 hit ratio 80%)
6. `qoo10_content`/`jp_detail` — URL 별 1회 영속, 재호출 X

잔여 LLM 호출 분담:
- 야간 batch (image_match, set_count 폴백) → **메인 PC ollama (14b/8b)**. 품질 부족해도 사장님 시트 검수에서 보정
- 1회성/대화형 (사장님 텔레그램 명령, brand_aliases 일괄 채우기, 코드 디버깅, SEO 콘텐츠 1건) → **Claude Code Max 구독** (`claude -p`)
- Codex CLI 는 ChatGPT Plus 구독 활용 시 옵션

**How to apply:**
- 새 AI 영역 추가 시 `.env` 의 `<DOMAIN>_MODEL` 기본값을 `ollama:<모델>` 로 제안
- Gemini / Claude API 같은 클라우드 모델은 "비교용 / 백업" 으로만 제안
- RTX 5080 16GB 기준 추천: 텍스트 `qwen2.5:14b` (9GB), 비전 `minicpm-v:8b` (5.5GB, 1.7초/장)
- llama3.2-vision:11b 는 minicpm-v 보다 3배 느림 → 비전은 minicpm-v 우선
- ollama 모델 추가 시 `ollama_client.py` 의 `supports_vision` 키워드 list 에 등록 필요 (vl/vision/llava/minicpm-v/moondream/gemma3 등)
- 새 모델 pull 후 backend 재시작 필수 (ollama 패키지 + .env 모델 변경 모두 반영)

**복잡 nested JSON schema 일 때 (예: JP detail 의 {jp,ko} pair × 다중 블록):**
- ❌ qwen3:14b — thinking 토큰이 max_tokens 의 상당 부분 잡아먹어 mid-output truncate. 단일 인용 / nested 구조 파괴 빈번.
- ✅ qwen2.5:14b — non-thinking, instruction follow 강함, JSON mode 안정.
- 패턴: 영역별 `<DOMAIN>_MODEL` env 분리 (router.py 의 lru_cache get_client_for). 단순 분류/추출은 qwen3, 복잡 schema 는 qwen2.5.
- 적용 사례: `QOO10_JP_DETAIL_MODEL=ollama:qwen2.5:14b` (qwen3 truncate → qwen2.5 안정), temperature 0.2 (복잡 schema 는 낮게)
