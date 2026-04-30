"""상세 페이지 이미지 (extras) vision 평가 (VVV-1).

각 한국 상품의 detail_image_paths 모든 이미지에 vision LLM (qwen2.5vl) 호출 →
0~1 score + 한 줄 묘사. 시트 우측 패널이 "좋은 컷" 선택 가능.

평가 기준:
  1.0 = 명확한 상품 컷, 누끼/배경 깨끗, 브랜드/상품 식별 가능
  0.7 = 사용 컷 (모델/생활), 상품 식별 OK
  0.4 = 부분 정보 (라벨 일부, 클로즈업)
  0.0 = 텍스트만, 무관 이미지, 저화질, 워터마크

env: VISION_MODEL (qwen2.5vl:7b 권장)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, update

logger = logging.getLogger(__name__)


_PROMPT = (
    "이 상세 페이지 이미지를 평가하세요.\n"
    "JSON 한 줄로 응답:\n"
    '{"score": 0.0~1.0, "desc": "한 줄 묘사 (30단어 이내)"}\n\n'
    "score 기준:\n"
    "1.0 = 명확한 상품 컷 (누끼/깨끗한 배경, 브랜드 식별 가능)\n"
    "0.7 = 사용 컷 (모델 사용, 생활 장면, 상품 식별 OK)\n"
    "0.4 = 부분 정보 (라벨 클로즈업, 일부 노출)\n"
    "0.0 = 텍스트 위주, 무관 이미지, 저화질, 큰 워터마크\n"
    "한국어/영문 OK. 다른 설명 없이 JSON 만."
)


async def _evaluate_one(image_path: str) -> dict:
    """단일 이미지 평가. 실패 시 빈 dict."""
    if not image_path or not Path(image_path).exists():
        return {}
    try:
        from app.services.llm.router import get_client_for
        client = get_client_for("image_match")  # VISION_MODEL
        result = await client.chat_with_image(
            [{"role": "user", "content": _PROMPT}],
            [image_path],
            temperature=0.0,
            max_tokens=128,
        )
        text = (result.text or "").strip()
        if not text:
            return {}
        # strip markdown code fence
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
        score = max(0.0, min(1.0, float(data.get("score") or 0.0)))
        desc = (data.get("desc") or "").strip()[:200]
        return {"score": score, "desc": desc}
    except Exception as e:
        logger.warning(f"[extras_eval] 평가 실패 {image_path[:60]}: {e}")
        return {}


async def evaluate_extras_for_product(
    domestic_product_id: int,
    image_paths: list[str],
    *,
    project_root: Path,
    skip_if_done: bool = True,
) -> dict:
    """한 상품의 모든 extras 평가 → DB UPDATE.

    image_paths: detail_image_paths JSON 디코드된 list (상대/절대 둘 다 OK)
    project_root: 상대경로 → 절대경로 변환용

    returns: {processed, ok, failed, items: [{file, score, desc}]}
    """
    from app.db.connection import async_session
    from app.db.models import DomesticProduct as _DP

    # skip_if_done: 이미 평가된 row 면 fetch 후 길이 비교
    if skip_if_done:
        async with async_session() as s:
            existing = (await s.execute(
                select(_DP.extras_eval_json).where(_DP.id == domestic_product_id).limit(1)
            )).first()
            if existing and existing[0]:
                try:
                    cur = json.loads(existing[0])
                    if isinstance(cur, list) and len(cur) >= len(image_paths):
                        return {"processed": 0, "skipped": True,
                                "items": cur, "message": "이미 평가됨"}
                except Exception:
                    pass

    items: list[dict] = []
    ok = 0
    failed = 0
    for p in image_paths:
        path_str = p
        # 상대경로 변환
        path_obj = Path(path_str)
        if not path_obj.is_absolute():
            path_obj = (project_root / path_str).resolve()
        abs_path = str(path_obj)

        eval_res = await _evaluate_one(abs_path)
        if eval_res:
            ok += 1
            items.append({
                "file": str(path_obj.name),
                "path": path_str,
                "score": eval_res.get("score", 0.0),
                "desc": eval_res.get("desc", ""),
            })
        else:
            failed += 1
            items.append({"file": str(path_obj.name), "path": path_str, "score": None, "desc": ""})
        # 작은 sleep — vision LLM 과부하 회피
        await asyncio.sleep(0.05)

    # DB UPDATE
    blob = json.dumps(items, ensure_ascii=False)
    try:
        async with async_session() as s:
            await s.execute(
                update(_DP).where(_DP.id == domestic_product_id).values(
                    extras_eval_json=blob,
                )
            )
            await s.commit()
    except Exception as e:
        logger.warning(f"[extras_eval] DB UPDATE 실패 d={domestic_product_id}: {e}")

    return {"processed": len(image_paths), "ok": ok, "failed": failed, "items": items}


async def run_extras_evaluation(
    target_date,
    *,
    keywords_jp: list[str] | None = None,
    only_accepted: bool = True,
    skip_if_done: bool = True,
    task_manager_obj=None,
    task_id: str | None = None,
) -> dict:
    """일자/키워드 기반 일괄 extras 평가.

    only_accepted: True 면 accepted/needs_review 매칭된 한국 SKU 만
    """
    from app.db.connection import async_session
    from app.db.models import (
        DomesticProduct as _DP, DomesticMatchCandidate as _DMC,
        Qoo10Product as _Q,
    )
    from app.services.domestic_image_pipeline import IMAGE_ROOT

    project_root = IMAGE_ROOT.parent

    # 대상 SKU 수집
    async with async_session() as s:
        if only_accepted:
            stmt = (
                select(_DP.id, _DP.detail_image_paths)
                .join(_DMC, _DMC.domestic_product_id == _DP.id)
                .join(_Q, _Q.id == _DMC.qoo10_product_id)
                .where(_DMC.decision.in_(["accepted", "needs_review"]))
                .where(_DP.detail_image_paths.is_not(None))
                .distinct()
            )
        else:
            stmt = (
                select(_DP.id, _DP.detail_image_paths)
                .join(_Q, _Q.search_keyword == _DP.search_keyword)
                .where(_DP.detail_image_paths.is_not(None))
                .distinct()
            )
        if keywords_jp:
            stmt = stmt.where(_Q.search_keyword.in_(keywords_jp))
        else:
            stmt = stmt.where(_Q.lookup_date == target_date)
        rows = (await s.execute(stmt)).all()

    if not rows:
        return {"processed": 0, "skipped": 0, "message": "대상 0건"}

    summary = {"products": len(rows), "ok": 0, "failed": 0, "skipped": 0, "total_images": 0}
    for idx, (d_id, paths_json) in enumerate(rows, 1):
        try:
            paths = json.loads(paths_json) if paths_json else []
        except Exception:
            paths = []
        if not paths:
            summary["skipped"] += 1
            continue
        try:
            res = await evaluate_extras_for_product(
                d_id, paths, project_root=project_root, skip_if_done=skip_if_done,
            )
            summary["total_images"] += res.get("processed", 0)
            summary["ok"] += res.get("ok", 0)
            summary["failed"] += res.get("failed", 0)
        except Exception as e:
            logger.warning(f"[extras_eval] product {d_id} 실패: {e}")
            summary["failed"] += 1

        if task_manager_obj and task_id:
            try:
                task_manager_obj.update_progress(
                    task_id, increment=1,
                    message=f"[{idx}/{len(rows)}] d={d_id} ({len(paths)} 이미지)",
                )
            except Exception:
                pass

    return summary


__all__ = ["run_extras_evaluation", "evaluate_extras_for_product"]
