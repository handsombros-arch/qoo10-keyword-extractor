"""매칭 정합도 낮은 keyword 에 대해 alt 키워드 생성 → 재검색 → 재매칭 (HHH-1).

흐름:
  1. last_auto_collected:{date} snapshot → 각 candidate
  2. 현재 best image_score 조회 (DomesticMatchCandidate.image_score MAX per qoo10_product_id)
  3. best < image_threshold (기본 0.5) 면 retry 대상
  4. retry: LLM 으로 alt keyword_kr 2~3개 생성 → Naver 검색 → DomesticProduct 저장 →
            cheapest qoo10 vs new domestic 이미지 매칭 → DomesticMatchCandidate INSERT
            (source_match_kind='alt_keyword')
  5. auto_build 다시 돌리면 alt 매칭이 accepted 면 자동 swap.

사용:
    from app.services.match_retry import run_match_retry
    summary = await run_match_retry(target_date, task_id=...)
"""
from __future__ import annotations

import asyncio
import logging
import os
import traceback
from pathlib import Path

from sqlalchemy import select, func

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    try:
        v = os.getenv(key)
        return float(v) if v is not None and v != "" else default
    except Exception:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        v = os.getenv(key)
        return int(v) if v is not None and v != "" else default
    except Exception:
        return default


async def _best_image_score(qoo10_product_id: int) -> float:
    """이 큐텐 product 의 모든 매칭 후보 중 최고 image_score."""
    from app.db.connection import async_session
    from app.db.models import DomesticMatchCandidate as _DMC

    async with async_session() as s:
        r = await s.execute(
            select(func.max(_DMC.image_score))
            .where(_DMC.qoo10_product_id == qoo10_product_id)
        )
        v = r.scalar()
    return float(v or 0.0)


async def _cheapest_qoo10_for_keyword(keyword_jp: str):
    """keyword_jp 의 큐텐 cheapest 1건 — alt 매칭 대상 큐텐 cover 로 사용."""
    from app.db.connection import async_session
    from app.db.models import Qoo10Product

    async with async_session() as s:
        r = await s.execute(
            select(
                Qoo10Product.id, Qoo10Product.product_name,
                Qoo10Product.product_name_ko, Qoo10Product.cover_image_url,
                Qoo10Product.price_jpy,
            )
            .where(Qoo10Product.search_keyword == keyword_jp)
            .where(Qoo10Product.cover_image_url.is_not(None))
            .where(Qoo10Product.price_jpy > 0)
            .order_by(Qoo10Product.price_jpy.asc())
            .limit(1)
        )
        return r.first()


async def _qoo10_top_names(keyword_jp: str, n: int = 8) -> list[str]:
    """LLM alt 생성용 — 큐텐 상위 N개 상품명 (가격 ASC)."""
    from app.db.connection import async_session
    from app.db.models import Qoo10Product

    async with async_session() as s:
        r = await s.execute(
            select(Qoo10Product.product_name)
            .where(Qoo10Product.search_keyword == keyword_jp)
            .where(Qoo10Product.price_jpy > 0)
            .order_by(Qoo10Product.price_jpy.asc())
            .limit(n)
        )
        return [row[0] for row in r.all() if row[0]]


async def _save_naver_results(products: list[dict]) -> int:
    """Naver scrape 결과 → DomesticProduct INSERT (search_keyword 는 products payload 에 포함)."""
    if not products:
        return 0
    from app.db.connection import async_session
    from app.db.sqlite_repo import SQLiteProductRepository

    try:
        async with async_session() as s:
            repo = SQLiteProductRepository(s)
            await repo.save_domestic_products(products)
        return len(products)
    except Exception as e:
        logger.warning(f"[match_retry] DB 저장 실패: {e}")
        return 0


async def _new_domestic_for_keyword(alt_kr: str, limit: int = 15) -> list:
    """방금 저장한 alt_kr 검색 결과 row 들 (가격 ASC)."""
    from app.db.connection import async_session
    from app.db.models import DomesticProduct

    async with async_session() as s:
        r = await s.execute(
            select(
                DomesticProduct.id, DomesticProduct.product_name,
                DomesticProduct.cover_image_url, DomesticProduct.image_local_path,
                DomesticProduct.price_krw,
            )
            .where(DomesticProduct.search_keyword == alt_kr)
            .where(DomesticProduct.cover_image_url.is_not(None))
            .where(DomesticProduct.price_krw > 0)
            .order_by(DomesticProduct.price_krw.asc())
            .limit(limit)
        )
        return r.all()


async def _match_one_pair(
    qid: int, q_cover_url: str, q_text: str,
    did: int, d_cover_url: str | None, d_local_path: str | None, d_text: str,
    img_threshold: float, text_threshold: float,
) -> dict:
    """단일 (큐텐, 한국) cover 매칭 → DomesticMatchCandidate INSERT.

    returns: {'image_score': float, 'name_score': float, 'decision': str}
    """
    from app.db.connection import async_session
    from app.db.models import DomesticMatchCandidate as _DMC, Qoo10Product as _Q, DomesticProduct as _DP
    from app.services.domestic_image_pipeline import download_to_temp, IMAGE_ROOT
    from app.services.llm.image_match import compare_two_images_async
    from app.services.llm.text_match import name_similarity
    from app.services.match_quality import compute_quality_score, decide_with_quality

    project_root = IMAGE_ROOT.parent

    def _abs(p):
        if not p:
            return None
        path = Path(p)
        if not path.is_absolute():
            path = (project_root / p).resolve()
        return str(path) if path.exists() else None

    q_tmp = await download_to_temp(q_cover_url) if q_cover_url else None
    d_path = _abs(d_local_path)
    d_tmp = None
    if not d_path and d_cover_url:
        d_tmp = await download_to_temp(d_cover_url)
        d_path = d_tmp

    try:
        text_score = name_similarity(q_text or "", d_text or "")
    except Exception:
        text_score = 0.0

    score, note, ok = 0.0, "", False
    if q_tmp and d_path:
        try:
            res = await compare_two_images_async(q_tmp, d_path)
            score = float(res.get("score") or 0.0)
            note = str(res.get("note") or "")
            ok = bool(res.get("ok"))
        except Exception as e:
            note = f"ERR: {e}"

    for tmp in (q_tmp, d_tmp):
        if tmp:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass

    # III-1: quality_score (description 자카드 포함)
    q_desc, d_desc = "", ""
    try:
        async with async_session() as s:
            qd = (await s.execute(
                select(_Q.cover_description).where(_Q.id == qid).limit(1)
            )).first()
            dd = (await s.execute(
                select(_DP.cover_description).where(_DP.id == did).limit(1)
            )).first()
            q_desc = (qd[0] if qd else "") or ""
            d_desc = (dd[0] if dd else "") or ""
    except Exception:
        pass
    quality_score, _ = compute_quality_score(score, text_score, q_desc, d_desc)

    if ok and score >= img_threshold and text_score >= text_threshold:
        decision = decide_with_quality(quality_score, image_ok=ok)
    else:
        decision = "rejected"

    try:
        async with async_session() as s:
            s.add(_DMC(
                qoo10_product_id=qid,
                domestic_product_id=did,
                source_match_kind="alt_keyword",
                name_score=text_score,
                image_score=score,
                image_match_note=note,
                quality_score=quality_score,
                decision=decision,
            ))
            await s.commit()
    except Exception as e:
        logger.warning(f"[match_retry] DMC INSERT 실패 q={qid} d={did}: {e}")

    return {"image_score": score, "name_score": text_score,
            "quality_score": quality_score, "decision": decision}


async def run_match_retry(
    target_date,
    *,
    task_manager_obj=None,
    task_id: str | None = None,
) -> dict:
    """retry 루프 — snapshot 기반 candidate 별 alt 키워드 시도.

    config (env):
      MATCH_RETRY_IMAGE_THRESHOLD   (기본 0.5) — best image_score 가 이 미만이면 retry
      MATCH_RETRY_SWAP_DELTA        (기본 0.15) — 새 score 가 기존+이만큼 좋아야 의미있는 개선
      MATCH_RETRY_ALT_COUNT         (기본 3) — kw 당 alt 수
      MATCH_RETRY_MAX_RESULTS       (기본 15) — Naver 결과 중 매칭할 최대 row 수
      MATCH_RETRY_MAX_PAIRS         (기본 5) — alt 당 매칭할 최대 row 수 (cost 제한)
      MATCH_RETRY_IMG_MATCH_THRESH  (기본 0.7) — accepted decision 임계
      MATCH_RETRY_TEXT_MATCH_THRESH (기본 0.10)

    returns:
      {date, scanned, retried, alt_searched, pairs_matched, improved, accepted, failed,
       per_keyword: [{kw_jp, kw_kr, before, after, alts: [...], improved: bool}...]}
    """
    import json as _json
    from app.db.connection import async_session
    from app.db.models import UserData
    from app.services.llm.keyword_alts import generate_keyword_alts_async
    from app.browser.manager import browser_manager
    from app.scrapers.m08_naver import NaverShoppingScraper

    image_threshold = _env_float("MATCH_RETRY_IMAGE_THRESHOLD", 0.5)
    swap_delta = _env_float("MATCH_RETRY_SWAP_DELTA", 0.15)
    alt_count = _env_int("MATCH_RETRY_ALT_COUNT", 3)
    max_results = _env_int("MATCH_RETRY_MAX_RESULTS", 15)
    max_pairs = _env_int("MATCH_RETRY_MAX_PAIRS", 5)
    img_match_thresh = _env_float("MATCH_RETRY_IMG_MATCH_THRESH", 0.7)
    text_match_thresh = _env_float("MATCH_RETRY_TEXT_MATCH_THRESH", 0.10)

    # III-1 — UserData 임계값 캐시 warm
    from app.services.match_quality import warm_quality_cache
    from app.services.auto_learning import load_reject_blocklist, is_blocked
    await warm_quality_cache()
    blocklist = await load_reject_blocklist()

    storage_key = f"last_auto_collected:{target_date}"
    async with async_session() as s:
        row = (await s.execute(
            select(UserData).where(UserData.key == storage_key)
        )).scalar_one_or_none()
    if not row:
        return {"error": f"snapshot 없음: {storage_key}"}

    try:
        payload = _json.loads(row.data)
    except Exception:
        return {"error": "snapshot 파싱 실패"}

    candidates = payload.get("candidates") or []
    if not candidates:
        return {"date": str(target_date), "scanned": 0, "retried": 0,
                "message": "candidates 0건"}

    summary = {
        "date": str(target_date),
        "scanned": len(candidates),
        "retried": 0,
        "alt_searched": 0,
        "pairs_matched": 0,
        "improved": 0,
        "accepted": 0,
        "failed": 0,
        "per_keyword": [],
    }

    scraper = None  # lazy — browser 필요

    def _bump(msg: str):
        logger.info(f"[match_retry] {msg}")
        if task_manager_obj and task_id:
            try:
                task_manager_obj.update_progress(task_id, increment=1, message=msg)
            except Exception:
                pass

    for idx, c in enumerate(candidates, 1):
        kw_jp = (c.get("keyword_jp") or "").strip()
        kw_kr = (c.get("keyword_kr") or "").strip()
        if not kw_jp or not kw_kr:
            continue

        # 큐텐 cheapest (alt 매칭 대상)
        q_row = await _cheapest_qoo10_for_keyword(kw_jp)
        if not q_row:
            continue
        q_id, q_name, q_name_ko, q_cover, q_price = q_row

        before_score = await _best_image_score(q_id)
        if before_score >= image_threshold:
            continue  # 이미 좋음 — skip

        summary["retried"] += 1
        per_kw = {
            "kw_jp": kw_jp, "kw_kr": kw_kr,
            "before": round(before_score, 3),
            "after": round(before_score, 3),
            "alts": [],
            "improved": False,
        }

        # alt 키워드 생성
        try:
            qoo10_names = await _qoo10_top_names(kw_jp, n=8)
            alts = await generate_keyword_alts_async(
                keyword_jp=kw_jp, keyword_kr=kw_kr, product_names=qoo10_names,
            )
        except Exception as e:
            logger.warning(f"[match_retry] alt 생성 실패 kw={kw_kr!r}: {e}")
            alts = []

        if not alts:
            _bump(f"[{idx}/{len(candidates)}] alt 0건 kw={kw_kr[:25]}")
            summary["per_keyword"].append(per_kw)
            continue

        alts = alts[:alt_count]
        _bump(f"[{idx}/{len(candidates)}] {len(alts)} alts kw={kw_kr[:25]} "
              f"before={before_score:.2f}")

        # scraper lazy init
        if scraper is None:
            from app.services.task_manager import task_manager as _tm
            scraper = NaverShoppingScraper(browser_manager, _tm)

        for a_idx, alt in enumerate(alts, 1):
            alt_kr = alt.get("keyword_kr", "")
            if not alt_kr:
                continue

            # Naver scrape
            try:
                nres = await scraper.run(keyword=alt_kr, max_results=max_results)
                products = nres.get("products") or []
            except Exception as e:
                logger.warning(f"[match_retry] m08 실패 alt={alt_kr!r}: {e}")
                products = []

            saved = await _save_naver_results(products)
            summary["alt_searched"] += 1

            if saved == 0:
                per_kw["alts"].append({"keyword_kr": alt_kr,
                                        "reason": alt.get("reason", ""),
                                        "saved": 0, "best_score": None})
                continue

            # 새 row 들 (가격 ASC, max_pairs 만)
            new_rows = await _new_domestic_for_keyword(alt_kr, limit=max_pairs)

            # 큐텐 1 vs 새 한국 N 매칭
            q_text = (q_name_ko or q_name or "")
            best_alt = before_score
            best_alt_decision = "rejected"
            for d_id, d_name, d_cover, d_local, d_price in new_rows:
                # KKK-1 A: blocklist
                if is_blocked(blocklist, q_id, d_id):
                    continue
                try:
                    res = await _match_one_pair(
                        q_id, q_cover, q_text + " " + kw_kr,
                        d_id, d_cover, d_local, d_name or "",
                        img_match_thresh, text_match_thresh,
                    )
                    summary["pairs_matched"] += 1
                    if res["decision"] == "accepted":
                        summary["accepted"] += 1
                    if res["image_score"] > best_alt:
                        best_alt = res["image_score"]
                        best_alt_decision = res["decision"]
                except Exception as e:
                    summary["failed"] += 1
                    logger.warning(f"[match_retry] 매칭 실패 q={q_id} d={d_id}: {e}")
                # 작은 sleep — vision LLM 과부하 회피
                await asyncio.sleep(0.05)

            per_kw["alts"].append({
                "keyword_kr": alt_kr,
                "reason": alt.get("reason", ""),
                "saved": saved,
                "best_score": round(best_alt, 3),
                "decision": best_alt_decision,
            })

        # 최종 best
        after_score = await _best_image_score(q_id)
        per_kw["after"] = round(after_score, 3)
        if after_score >= before_score + swap_delta:
            per_kw["improved"] = True
            summary["improved"] += 1

        summary["per_keyword"].append(per_kw)

        _bump(f"[{idx}/{len(candidates)}] kw={kw_kr[:25]} "
              f"before={before_score:.2f} after={after_score:.2f} "
              f"{'✓ 개선' if per_kw['improved'] else '·'}")

    return summary


__all__ = ["run_match_retry"]
