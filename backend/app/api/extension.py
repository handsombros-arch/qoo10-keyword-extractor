"""크롬 확장 (qoo10-helper-extension) 통신용 큐 API.

흐름:
    백엔드 ─ POST /api/ext/queue ─▶ in-memory 큐
    확장 ──── GET  /api/ext/queue/next ───▶ pending job 1건 반환 (in_progress 전환)
    확장 ──── POST /api/ext/result ───────▶ URL별 결과 수신
    확장 ──── POST /api/ext/queue/complete ▶ 작업 완료 보고
    백엔드 ─ GET  /api/ext/status?job_id ─▶ ext_client 폴링용

Phase 1 — in-memory. 단일 사장님 사용이라 충분. 향후 DB 영속화 검토.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ext", tags=["extension"])


class JobStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class UrlStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class ScrapeJob:
    job_id: str
    urls: list[dict]                       # [{ url, keyword_jp?, keyword_kr? }]
    config: dict
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    url_statuses: dict[str, UrlStatus] = field(default_factory=dict)
    results: dict[str, dict] = field(default_factory=dict)   # url → {status, data?, error?, elapsed_ms}
    last_error: str | None = None

    def summary(self) -> dict:
        success = sum(1 for s in self.url_statuses.values() if s == UrlStatus.SUCCESS)
        errors = sum(1 for s in self.url_statuses.values() if s == UrlStatus.ERROR)
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "total": len(self.urls),
            "success": success,
            "errors": errors,
            "pending": len(self.urls) - success - errors,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "last_error": self.last_error,
        }


# ──── 큐 (process-local) ─────────────────────────────────────────
_jobs: dict[str, ScrapeJob] = {}
_pending_order: list[str] = []   # FIFO
_lock = asyncio.Lock()


async def _next_pending() -> ScrapeJob | None:
    async with _lock:
        for jid in list(_pending_order):
            j = _jobs.get(jid)
            if j and j.status == JobStatus.PENDING:
                j.status = JobStatus.IN_PROGRESS
                j.started_at = datetime.now()
                _pending_order.remove(jid)
                return j
        return None


# ──── API: 작업 등록 ─────────────────────────────────────────────
@router.post("/queue")
async def register_job(body: dict) -> dict:
    job_id = body.get("job_id") or f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
    urls_raw = body.get("urls") or []
    if not isinstance(urls_raw, list) or not urls_raw:
        raise HTTPException(400, "urls 배열이 필요합니다")
    urls: list[dict] = []
    for item in urls_raw:
        if isinstance(item, str):
            urls.append({"url": item})
        elif isinstance(item, dict) and item.get("url"):
            urls.append({
                "url": item["url"],
                "keyword_jp": item.get("keyword_jp"),
                "keyword_kr": item.get("keyword_kr"),
            })
    if not urls:
        raise HTTPException(400, "유효한 URL 0개")

    config = body.get("config") or {}
    job = ScrapeJob(
        job_id=job_id,
        urls=urls,
        config=config,
        url_statuses={u["url"]: UrlStatus.PENDING for u in urls},
    )
    async with _lock:
        if job_id in _jobs:
            raise HTTPException(409, f"job_id {job_id} 이미 존재")
        _jobs[job_id] = job
        _pending_order.append(job_id)

    logger.info(f"[ext.queue] 등록 {job_id} ({len(urls)}건)")
    return {
        "job_id": job_id,
        "total_urls": len(urls),
        "status": job.status.value,
    }


# ──── API: 확장이 다음 작업 폴링 ─────────────────────────────────
@router.get("/queue/next")
async def next_job() -> Response:
    job = await _next_pending()
    if not job:
        return Response(status_code=204)
    return Response(
        media_type="application/json",
        content=_dump_job_for_extension(job),
    )


def _dump_job_for_extension(job: ScrapeJob) -> str:
    import json
    return json.dumps({
        "job_id": job.job_id,
        "urls": job.urls,
        "config": job.config,
    }, ensure_ascii=False)


# ──── API: 확장 → URL별 결과 수신 ───────────────────────────────
@router.post("/result")
async def result_url(body: dict) -> dict:
    job_id = body.get("job_id")
    url = body.get("url")
    status = body.get("status")
    if not job_id or not url:
        raise HTTPException(400, "job_id, url 필수")

    async with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, f"unknown job_id {job_id}")
        if status == "success":
            job.url_statuses[url] = UrlStatus.SUCCESS
            job.results[url] = {
                "status": "success",
                "data": body.get("data") or {},
                "elapsed_ms": body.get("elapsed_ms"),
                "received_at": datetime.now().isoformat(),
            }
        else:
            job.url_statuses[url] = UrlStatus.ERROR
            err = body.get("error") or "unknown error"
            job.results[url] = {
                "status": "error",
                "error": err,
                "elapsed_ms": body.get("elapsed_ms"),
                "received_at": datetime.now().isoformat(),
            }
            job.last_error = err

    # Phase 2 후속: keyword_jp/kr → domestic_products UPSERT
    # (지금은 결과만 보관)
    return {"ok": True, "url": url, "status": status}


# ──── API: 확장 → 작업 완료 ─────────────────────────────────────
@router.post("/queue/complete")
async def complete_job(body: dict) -> dict:
    job_id = body.get("job_id")
    if not job_id:
        raise HTTPException(400, "job_id 필수")
    async with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, f"unknown job_id {job_id}")
        # 모든 URL 처리됐는지 확인
        unfinished = [u for u, s in job.url_statuses.items() if s == UrlStatus.PENDING]
        if unfinished:
            job.status = JobStatus.FAILED
            job.last_error = f"{len(unfinished)}건 미처리 (확장 중단 추정)"
        else:
            job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now()

    logger.info(f"[ext.queue] 완료 {job_id} {job.summary()}")
    return job.summary()


# ──── API: ext_client 폴링용 status ─────────────────────────────
@router.get("/status")
async def status(job_id: str | None = None) -> dict:
    async with _lock:
        if job_id:
            job = _jobs.get(job_id)
            if not job:
                raise HTTPException(404, f"unknown job_id {job_id}")
            return {
                "summary": job.summary(),
                "url_statuses": {u: s.value for u, s in job.url_statuses.items()},
                "results": job.results,
            }
        # 전체 큐 요약 (대시보드용)
        return {
            "jobs": [j.summary() for j in _jobs.values()],
            "pending_order": list(_pending_order),
        }


# ──── API: 작업 삭제 (운영 편의) ────────────────────────────────
@router.delete("/queue/{job_id}")
async def delete_job(job_id: str) -> dict:
    async with _lock:
        if job_id not in _jobs:
            raise HTTPException(404)
        del _jobs[job_id]
        if job_id in _pending_order:
            _pending_order.remove(job_id)
    return {"ok": True, "job_id": job_id}


# ──── 디버그/테스트용 — 큐 비우기 ────────────────────────────────
@router.post("/queue/clear")
async def clear_queue() -> dict:
    async with _lock:
        n = len(_jobs)
        _jobs.clear()
        _pending_order.clear()
    return {"cleared": n}
