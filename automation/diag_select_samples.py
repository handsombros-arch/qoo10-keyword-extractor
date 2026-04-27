"""logs/llm_calls 의 translate 호출 중 잔존 가나 케이스 5개 샘플 선정 + JSON 저장."""
import sys, json, re
from pathlib import Path

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ANY_KANA = re.compile(r"[぀-ヿ]")
GENMUN = "원문:"  # '원문:'

records = []
for fp in ["logs/llm_calls/2026-04-27.jsonl", "logs/llm_calls/2026-04-28.jsonl"]:
    p = Path(fp)
    if not p.exists(): continue
    with p.open(encoding="utf-8") as f:
        for line in f:
            try: r = json.loads(line)
            except Exception: continue
            if r.get("domain") != "translate": continue
            content = r.get("input", {}).get("messages", [{}])[0].get("content", "")
            idx = content.rfind(GENMUN)
            if idx < 0: continue
            jp = content[idx+len(GENMUN):].strip()
            out = r.get("output")
            ko = out.get("text", "") if isinstance(out, dict) else str(out or "")
            if jp and ko and ANY_KANA.search(ko):
                records.append((jp, ko))

print(f"translate 호출 잔존 가나 케이스: {len(records)}")

# 다양한 패턴 5건
patterns = [
    ("メラメイト", "メラメイト_브랜드"),       # メラメイト
    ("オリーブヤング", "올리브영_매장"),  # オリーブヤング
    ("トイストーリー", "토이스토리_캐릭터"),  # トイストーリー
    ("マイメロディ", "마이멜로디_캐릭터"),     # マイメロディ
    ("ハパクリスティン", "하파크리스틴_브랜드"),  # ハパクリスティン
]
samples = []
for pat, tag in patterns:
    for jp, ko in records:
        if pat in jp:
            samples.append({"jp": jp, "ko_7b": ko, "tag": tag})
            break

print(f"선정: {len(samples)}")
for s in samples:
    print(f"  [{s['tag']}]")
    print(f"    jp: {s['jp'][:80]}")
    print(f"    7b ko: {s['ko_7b'][:80]}")

out = Path("automation/diag_samples5.json")
out.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"saved: {out}")
