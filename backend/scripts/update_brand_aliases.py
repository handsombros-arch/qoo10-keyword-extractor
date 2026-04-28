"""brands.aliases JSON 채우기.

기존 brand row 의 추가 표기 (잘못된 번역, 다른 한자/카타카나/로마자) 를
aliases JSON 배열에 누적 저장. _match_in_whitelist 가 매칭에 사용.

사용:
    cd backend
    python -m scripts.update_brand_aliases                    # 알려진 시드만
    python -m scripts.update_brand_aliases --kr 달바 --add 다루바 dAlba
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db.connection import async_session, engine  # noqa: E402
from app.db.models import Brand  # noqa: E402

# kr → 추가 alias 목록. 번역기 의역, 다른 표기법 등 누적.
_KNOWN_ALIASES: dict[str, list[str]] = {
    "달바": ["다루바", "dAlba", "ダルバ"],
    "메디큐브": ["メディキューブ"],
    "라카": ["laka", "ラカ"],
    "아누아": ["anua", "アヌア"],
    "코스노리": ["cosnori"],
    "하파크리스틴": ["hapakristin", "ハパクリスティン"],
}


async def update_aliases(kr: str, new_aliases: list[str]) -> tuple[bool, list[str]]:
    """해당 kr 의 brand 에 alias 추가 (중복 제거). (성공여부, 최종 aliases) 반환."""
    new_aliases = [a.strip() for a in new_aliases if a and a.strip()]
    if not new_aliases:
        return False, []

    async with async_session() as session:
        b = (await session.execute(
            select(Brand).where(Brand.kr == kr)
        )).scalar_one_or_none()
        if not b:
            return False, []

        try:
            current = json.loads(b.aliases or "[]")
            if not isinstance(current, list):
                current = []
        except json.JSONDecodeError:
            current = []

        merged = list(dict.fromkeys(current + new_aliases))  # 순서 보존 dedup
        b.aliases = json.dumps(merged, ensure_ascii=False)
        await session.commit()
        return True, merged


async def main() -> int:
    p = argparse.ArgumentParser(description="brands.aliases 업데이트")
    p.add_argument("--kr", help="단일 brand kr (지정 시 --add 와 함께)")
    p.add_argument("--add", nargs="+", help="추가 alias 들 (--kr 필수)")
    args = p.parse_args()

    if args.kr and args.add:
        ok, merged = await update_aliases(args.kr, args.add)
        if ok:
            print(f"[OK] {args.kr} aliases = {merged}")
            await engine.dispose()
            return 0
        print(f"[ERR] kr={args.kr!r} brand 없음")
        await engine.dispose()
        return 1

    # 시드 모드 — 알려진 매핑 일괄 적용
    print(f"[seed_aliases] 알려진 매핑 {len(_KNOWN_ALIASES)}개 시도")
    ok_count = miss_count = 0
    for kr, aliases in _KNOWN_ALIASES.items():
        ok, merged = await update_aliases(kr, aliases)
        if ok:
            ok_count += 1
            print(f"  [OK]   {kr:20s} → {merged}")
        else:
            miss_count += 1
            print(f"  [MISS] {kr:20s} (brand 없음)")
    print(f"[seed_aliases] 완료 — OK {ok_count}, MISS {miss_count}")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
