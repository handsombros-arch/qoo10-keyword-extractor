"""LLM 영역별 단발 호출 검증 (CLI).

긴 `python -c "..."` 명령 대신 짧게 호출하는 헬퍼.

사용:
    cd backend

    # 1) 인자 없이 → 텍스트 영역 3개 샘플로 한 번씩 시연 (vision 은 이미지 필요)
    python -m scripts.test_llm

    # 2) 영역명만 → 그 영역의 샘플들만
    python -m scripts.test_llm brand
    python -m scripts.test_llm category
    python -m scripts.test_llm set_count

    # 3) 영역 + 직접 입력
    python -m scripts.test_llm brand "스킨1004 마다가스카르 센텔라"
    python -m scripts.test_llm category "아누아 토너"
    python -m scripts.test_llm set_count "신라면 5봉지"

    # 4) 비전 — 이미지 경로 필요
    python -m scripts.test_llm vision "C:\\path\\to\\image.jpg"
    python -m scripts.test_llm vision "C:\\path\\to\\image.jpg" "07.식품"

    # 5) 비용 잔액 조회 (LLM 호출 0)
    python -m scripts.test_llm budget
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.llm.brand import is_brand_keyword  # noqa: E402
from app.services.llm.category import classify_category  # noqa: E402
from app.services.llm.set_count import extract_set_count  # noqa: E402
from app.services.llm.vision import (  # noqa: E402
    count_packages_in_image,
    score_product_image,
)
from app.services.llm._budget import budget_status  # noqa: E402


_SAMPLES: dict[str, list[str]] = {
    "brand": [
        "아누아 어성초 토너",
        "스킨1004 마다가스카르 센텔라",
        "수분크림 추천",
    ],
    "category": [
        "아누아 어성초 토너",
        "신라면 블랙 5개입",
        "AirPods Pro",
    ],
    "set_count": [
        "아누아 어성초 토너 3개입",
        "마스크팩 × 5",
        "AirPods Pro",
    ],
}

_TEXT_DOMAINS = list(_SAMPLES.keys())
_ALL_DOMAINS = _TEXT_DOMAINS + ["vision", "budget"]


def _format(result) -> str:
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return repr(result)


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n {title}\n{'=' * 60}")


def _run_text(domain: str, value: str) -> None:
    print(f"\n>>> {domain}({value!r})")
    if domain == "brand":
        out = is_brand_keyword(value)
    elif domain == "category":
        out = classify_category(value)
    elif domain == "set_count":
        out = extract_set_count(value)
    else:
        print(f"[ERR] 알 수 없는 텍스트 영역: {domain!r}")
        sys.exit(2)
    print(_format(out))


def _run_vision(image_path: str, category: str = "기타") -> None:
    p = Path(image_path)
    if not p.exists():
        print(f"[ERR] 이미지 파일 없음: {image_path}")
        sys.exit(2)

    print(f"\n>>> vision.score({p.name!r}, category={category!r})")
    print(_format(score_product_image(image_path, category)))

    print(f"\n>>> vision.count({p.name!r})")
    print(_format(count_packages_in_image(image_path)))


def _run_budget() -> None:
    print(f"\n>>> budget_status()")
    print(_format(budget_status()))


def _print_usage() -> None:
    print("사용법:")
    print("  python -m scripts.test_llm                      # 텍스트 영역 샘플 전체")
    print("  python -m scripts.test_llm <영역>                # 영역의 샘플들")
    print('  python -m scripts.test_llm <영역> "<입력>"        # 텍스트 단발 호출')
    print('  python -m scripts.test_llm vision "<이미지경로>" [카테고리]')
    print("  python -m scripts.test_llm budget               # 오늘자 비용 잔액")
    print(f"  영역: {', '.join(_ALL_DOMAINS)}")


def main() -> int:
    args = sys.argv[1:]

    if not args:
        for d in _TEXT_DOMAINS:
            _print_section(d)
            for v in _SAMPLES[d]:
                _run_text(d, v)
        print()
        print("(vision 은 이미지 경로 필요 — `test_llm vision <path>` 로 별도 실행)")
        return 0

    domain = args[0]

    if domain == "budget":
        if len(args) > 1:
            _print_usage()
            return 2
        _run_budget()
        return 0

    if domain == "vision":
        if len(args) < 2:
            print("[ERR] vision 은 이미지 경로 인자 필요")
            _print_usage()
            return 2
        image_path = args[1]
        category = args[2] if len(args) > 2 else "기타"
        _run_vision(image_path, category)
        return 0

    if domain in _SAMPLES:
        if len(args) == 1:
            _print_section(domain)
            for v in _SAMPLES[domain]:
                _run_text(domain, v)
            return 0
        if len(args) == 2:
            _run_text(domain, args[1])
            return 0

    _print_usage()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
