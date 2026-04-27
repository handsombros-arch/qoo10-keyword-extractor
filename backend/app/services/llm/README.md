# LLM 추론 인프라

영역별로 다른 모델(Ollama 로컬 / Gemini 클라우드)을 `.env` 로 라우팅하는 추상화 레이어.

## 빠른 사용법

```python
from app.services.llm import get_client_for, load_prompt

# 영역명만 주면 .env 의 BRAND_MODEL 에 따라 자동 라우팅 + 자동 로깅
client = get_client_for("brand")
prompt = load_prompt("brand_detection")

result = await client.chat([
    {"role": "system", "content": prompt},
    {"role": "user", "content": "에이프릴 스킨"},
])
print(result.text, result.latency_ms)
```

## 디렉토리

```
llm/
├── base.py              # LLMClient ABC, ChatResult dataclass
├── ollama_client.py     # Ollama (로컬)
├── gemini_client.py     # Gemini (클라우드, 텍스트+비전)
├── router.py            # get_client_for(domain) — 영역명 → 클라이언트
├── logger.py            # logs/llm_calls/{date}.jsonl 자동 기록
├── test_connection.py   # 자가 테스트 (python -m ...)
└── prompts/             # 영역별 프롬프트 .txt
```

## 자가 테스트

```bash
cd backend
python -m app.services.llm.test_connection
```

설정된 `*_MODEL` 항목들의 provider 별로 hello world 호출 → 모두 성공하면 `✅ 모든 LLM 백엔드 정상`.

## 모델 비교 (자기 도메인 데이터로)

```bash
cd C:\Users\Admin\qoo10-keyword-extractor
python -m automation.eval.eval_runner brand_detection \
    --models gemini:gemini-2.5-flash ollama:qwen2.5:14b
```

→ `automation/eval/reports/brand_detection_<timestamp>.md` 자동 생성.

테스트 케이스는 `automation/eval/test_cases/<영역>.jsonl` 에 한 줄 한 케이스:
```json
{"input": {"messages": [{"role": "user", "content": "에이프릴 스킨"}]}, "expected": "true"}
```

---

## 비용 0 시작 (현재 기본값)

`.env.example` 의 모든 `*_MODEL` 은 `gemini:gemini-2.5-flash` 로 시작합니다. Gemini 2.5 Flash 는 가장 저렴한 클라우드 모델이고, **Google AI Studio 무료 티어 (분당 15회 / 일 1500회)** 안에서 동작 가능. 일일 트렌드 670개 × 5영역 = 3,350회 추론도 무료로 충분.

본격 사용 전 한도가 부족해지면 → 아래 로컬 전환.

---

## RTX 5080 (16GB VRAM) 로컬 전환 가이드

### 권장 모델 (Blackwell 16GB 기준)

| 영역 | 모델 | VRAM | 속도 | 정확도 평가 |
|---|---|---|---|---|
| 카테고리 (3분류) | `qwen2.5:7b` | ~5GB | 매우 빠름 | 🟢 95%+. 7B로 충분 |
| 브랜드 판별 | `qwen2.5:14b` | ~10GB Q4 | 빠름 (1-2s) | 🟡 화이트리스트 + LLM 하이브리드 권장 |
| 세트 개수 추출 | `qwen2.5:14b` | ~10GB Q4 | 빠름 | 🟢 정규식 + LLM 폴백 시 95%+ |
| 세트 구성 제안 | `qwen2.5:14b` | ~10GB Q4 | 빠름 | 🟡 룰 기반이 더 적합. LLM은 보조 |
| **비전 (이미지 적합성)** | `qwen2.5-vl:7b` | ~6GB | 보통 | 🟡 한국 K뷰티 패키지 학습 부족 |
| 비전 (대안) | `llama3.2-vision:11b` | ~8GB | 보통 | 🟡 |
| 고성능 옵션 | `qwen2.5:32b-instruct-q3_K_M` | ~14GB Q3 | 느림 (3-5s) | 🟢 Gemini 근접 |

### 전환 절차

**1) Ollama 설치 (Windows)**
```
https://ollama.com/download/windows  →  exe 설치
```
설치 후 `localhost:11434` 자동 실행. 작업 표시줄 아이콘 확인.

**2) 모델 pull (한 번만, 디스크 사용량 주의)**
```bash
# 가벼운 영역 먼저
ollama pull qwen2.5:7b              # ~4.7GB
ollama pull qwen2.5:14b             # ~9GB

# 비전 추가
ollama pull qwen2.5-vl:7b           # ~5.4GB
# 또는
ollama pull llama3.2-vision:11b     # ~7.8GB

# (선택) 32B 고정확도 옵션
ollama pull qwen2.5:32b-instruct-q3_K_M   # ~14GB
```

**3) `.env` 수정 — 영역별 점진적 전환**

비용·속도가 가장 부담되는 영역부터 하나씩 옮기는 걸 권장:

```env
# 비용이 큰 비전부터 로컬로
VISION_MODEL=ollama:qwen2.5-vl:7b

# 빈번한 호출 영역
CATEGORY_MODEL=ollama:qwen2.5:7b
SET_COUNT_MODEL=ollama:qwen2.5:14b

# 정확도 민감한 영역은 Gemini 유지
BRAND_MODEL=gemini:gemini-2.5-flash
```

**4) 자가 테스트로 확인**
```bash
cd backend
python -m app.services.llm.test_connection
```

**5) 본인 데이터로 비교 (필수)**

추정치만 믿지 말고 실제 한국 화장품/식품 키워드로 측정:
```bash
python -m automation.eval.eval_runner brand_detection \
    --models gemini:gemini-2.5-flash ollama:qwen2.5:14b ollama:qwen2.5:32b-instruct-q3_K_M
```
리포트의 정확도와 p50/p95 보고 결정.

### 5080 운영 팁

- **Ollama 는 모델을 자동 언로드** (`OLLAMA_KEEP_ALIVE`, 기본 5분). 빈번히 쓰면 keep alive 늘리면 좋음. (영구: `OLLAMA_KEEP_ALIVE=24h`)
- **동시 요청 제한**: 한 모델에 동시 1-2개. 다른 모델 동시 로딩하면 VRAM OOM. → `eval_runner` 는 순차 실행.
- **양자화 표기 (Q4_K_M, Q3_K_M)**: 숫자 작을수록 가볍고 정확도 손실. 기본 ollama 태그(`qwen2.5:14b`)는 Q4_K_M.
- **비전 모델 한국어**: Qwen-VL/LLaVA 모두 한국 K뷰티 상품 패키지 학습이 약함. 정확도 ≥85% 필요하면 Gemini 유지 권장. eval로 직접 확인.
- **5080 Blackwell**: Ollama 0.4+ 에서 CUDA 12.4 자동 인식. 구버전이면 `ollama --version` 으로 확인 후 업데이트.

### 비용 감각 비교

| 시나리오 | 일일 호출 수 | Gemini Flash | 로컬 (전기) |
|---|---|---|---|
| 트렌드 670개 × 5영역 | 3,350회 | ~$0.10/일 | ~$0.05/일 (전기료) |
| 비전 100장/일 | 100회 | ~$0.30/일 | ~$0.02/일 |
| 합계 | | **~$12/월** | **~$2/월** + 시간 |

소규모 운영이면 Gemini 가 시간 대비 합리적. 비전이나 일배치가 늘어나면 로컬 전환 효과 큼.

---

## 확장: 새 영역 추가하기

1. `prompts/<영역명>.txt` 작성
2. `.env` 에 `<영역명대문자>_MODEL=...` 한 줄 추가
3. 호출부에서:
   ```python
   client = get_client_for("<영역명>")
   prompt = load_prompt("<프롬프트파일명>")
   result = await client.chat([{"role": "system", "content": prompt}, ...])
   ```

코드 수정 없이 모델만 바꾸려면 `.env` 만 고치고 백엔드 재시작.

## 호출 로그

`logs/llm_calls/2026-04-27.jsonl` 한 줄당 한 호출:
```json
{"ts": "...", "domain": "brand", "model": "ollama:qwen2.5:14b",
 "input": {"messages": [...]}, "output": "...",
 "input_tokens": 412, "output_tokens": 18, "latency_ms": 740,
 "ok": true, "error": null}
```

비활성화: `.env` 에 `LLM_LOG_ENABLED=false`.
