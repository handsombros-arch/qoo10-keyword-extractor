"""5개 샘플을 4개 모델 (qwen2.5:7b/14b, qwen3:14b, gemini-2.5-flash) 로 호출 비교.

ollama 직접 호출 (캐시 우회) + google.genai 사용.
프롬프트는 backend/app/services/llm/prompts/jp_ko_translation.txt 그대로.
"""
import sys, os, json, time, asyncio, re
from pathlib import Path

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ANY_KANA = re.compile(r"[぀-ヿ]")

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "backend/app/services/llm/prompts/jp_ko_translation.txt"
SAMPLES_PATH = ROOT / "automation/diag_samples5.json"

PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")
SAMPLES = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))


def build_prompt(jp: str) -> str:
    return PROMPT_TEMPLATE.replace("{product_name}", jp)


def parse_ko(text: str) -> str:
    """JSON {"ko": "..."} 파싱."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    try:
        d = json.loads(s)
        if isinstance(d, dict): return (d.get("ko") or "").strip()
    except Exception:
        pass
    # 폴백: raw 첫 줄
    return s.splitlines()[0].strip() if s else ""


async def call_ollama(model: str, jp: str) -> tuple[str, float]:
    from ollama import AsyncClient
    client = AsyncClient(host=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    t0 = time.time()
    try:
        resp = await client.chat(
            model=model,
            messages=[{"role": "user", "content": build_prompt(jp)}],
            options={"temperature": 0.0, "num_predict": 512},
            format="json",
        )
        text = resp["message"]["content"]
        return parse_ko(text), time.time() - t0
    except Exception as e:
        return f"[ERR: {e}]", time.time() - t0


def call_gemini(model: str, jp: str) -> tuple[str, float]:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "[NO_API_KEY]", 0.0
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    t0 = time.time()
    try:
        resp = m.generate_content(
            build_prompt(jp),
            generation_config={"temperature": 0.0, "response_mime_type": "application/json", "max_output_tokens": 512},
        )
        return parse_ko(resp.text), time.time() - t0
    except Exception as e:
        return f"[ERR: {e}]", time.time() - t0


async def main():
    models = [
        ("ollama:qwen2.5:7b", "qwen2.5:7b", "ollama"),
        ("ollama:qwen2.5:14b", "qwen2.5:14b", "ollama"),
        ("ollama:qwen3:14b", "qwen3:14b", "ollama"),
        ("gemini:gemini-2.5-flash", "gemini-2.5-flash", "gemini"),
    ]

    results = []
    for i, sample in enumerate(SAMPLES, 1):
        jp = sample["jp"]
        tag = sample["tag"]
        print(f"\n{'='*60}")
        print(f"[샘플 {i}] {tag}")
        print(f"  jp: {jp[:90]}")
        sample_res = {"sample": sample, "models": {}}
        for label, model_name, kind in models:
            if kind == "ollama":
                ko, lat = await call_ollama(model_name, jp)
            else:
                ko, lat = call_gemini(model_name, jp)
            kana_left = bool(ANY_KANA.search(ko))
            mark = "X" if kana_left else "✓"
            print(f"  {label:<32} ({lat:>5.1f}s) {mark} {ko[:90]}")
            sample_res["models"][label] = {"ko": ko, "latency_s": round(lat, 2), "kana_left": kana_left}
        results.append(sample_res)

    out = ROOT / "automation/diag_compare_results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out}")

    # 요약
    print(f"\n{'='*60}")
    print("요약 (가나 잔존 / 5건 중)")
    for label, _, _ in models:
        n_left = sum(1 for r in results if r["models"][label]["kana_left"])
        avg_lat = sum(r["models"][label]["latency_s"] for r in results) / len(results)
        print(f"  {label:<32} 가나잔존 {n_left}/5  평균 {avg_lat:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
