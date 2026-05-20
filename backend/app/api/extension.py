"""크롬 확장 (qoo10-helper-extension) 통신용 큐 API.

흐름:
    백엔드 ─ POST /api/ext/queue ─▶ SQLite 영속 큐
    확장 ──── GET  /api/ext/queue/next ───▶ pending job 1건 반환 (in_progress 전환)
    확장 ──── POST /api/ext/result ───────▶ URL별 결과 수신
    확장 ──── POST /api/ext/queue/complete ▶ 작업 완료 보고
    백엔드 ─ GET  /api/ext/status?job_id ─▶ ext_client 폴링용

Phase 2 (B 작업): SQLite 영속화 + TTL/stale 정리.
  - data/ext_queue.db 에 모든 mutation write-through
  - 백엔드 재시작 시 큐 복원 (in_progress 던 작업은 PENDING 으로 되돌림 = 재처리)
  - in_progress 10분 stuck → FAILED (확장 SW 죽음 추정)
  - completed/failed 1시간 경과 → purge
"""

from __future__ import annotations

import asyncio
import json as _json_mod
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Response

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ext", tags=["extension"])

# ── 영속화 / TTL 정책 ─────────────────────────────────────
_DB_PATH = Path(settings.DATA_DIR) / "ext_queue.db"
_DB_LOCK = threading.Lock()

_STALE_IN_PROGRESS_SECONDS = 600   # 10분 stuck → FAILED (확장 SW 사망 추정)
_PURGE_TERMINAL_SECONDS = 3600     # completed/failed 1시간 경과 → 삭제
_CLEANUP_INTERVAL_SECONDS = 60


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


# ──── 큐 (메모리 핫 + SQLite 영속) ────────────────────────────────
_jobs: dict[str, ScrapeJob] = {}
_pending_order: list[str] = []   # FIFO
_lock = asyncio.Lock()


# ──── SQLite 헬퍼 (sync, threading.Lock 보호) ─────────────────────
def _ensure_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _DB_LOCK:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ext_jobs (
                    job_id TEXT PRIMARY KEY,
                    urls_json TEXT,
                    config_json TEXT,
                    status TEXT,
                    created_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    last_error TEXT,
                    url_statuses_json TEXT,
                    results_json TEXT
                )"""
            )
            conn.commit()
        finally:
            conn.close()


def _save_job_sync(job: ScrapeJob) -> None:
    with _DB_LOCK:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            conn.execute(
                """INSERT OR REPLACE INTO ext_jobs (
                    job_id, urls_json, config_json, status,
                    created_at, started_at, completed_at, last_error,
                    url_statuses_json, results_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.job_id,
                    _json_mod.dumps(job.urls, ensure_ascii=False),
                    _json_mod.dumps(job.config, ensure_ascii=False),
                    job.status.value,
                    job.created_at.isoformat(),
                    job.started_at.isoformat() if job.started_at else None,
                    job.completed_at.isoformat() if job.completed_at else None,
                    job.last_error,
                    _json_mod.dumps({u: s.value for u, s in job.url_statuses.items()}, ensure_ascii=False),
                    _json_mod.dumps(job.results, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def _delete_job_sync(job_id: str) -> None:
    with _DB_LOCK:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            conn.execute("DELETE FROM ext_jobs WHERE job_id = ?", (job_id,))
            conn.commit()
        finally:
            conn.close()


def _load_all_jobs_sync() -> dict[str, ScrapeJob]:
    if not _DB_PATH.exists():
        return {}
    with _DB_LOCK:
        conn = sqlite3.connect(str(_DB_PATH))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM ext_jobs").fetchall()
        finally:
            conn.close()
    out: dict[str, ScrapeJob] = {}
    for r in rows:
        try:
            job = ScrapeJob(
                job_id=r["job_id"],
                urls=_json_mod.loads(r["urls_json"]),
                config=_json_mod.loads(r["config_json"]),
                status=JobStatus(r["status"]),
                created_at=datetime.fromisoformat(r["created_at"]),
                started_at=datetime.fromisoformat(r["started_at"]) if r["started_at"] else None,
                completed_at=datetime.fromisoformat(r["completed_at"]) if r["completed_at"] else None,
                last_error=r["last_error"],
                url_statuses={u: UrlStatus(s) for u, s in _json_mod.loads(r["url_statuses_json"]).items()},
                results=_json_mod.loads(r["results_json"]),
            )
            out[job.job_id] = job
        except Exception as e:
            logger.warning(f"[ext.queue] job {r['job_id']} 복원 실패: {e}")
    return out


async def _save_job(job: ScrapeJob) -> None:
    """비동기 wrapper — sqlite write 를 thread 로 위임."""
    await asyncio.to_thread(_save_job_sync, job)


async def _delete_job_db(job_id: str) -> None:
    await asyncio.to_thread(_delete_job_sync, job_id)


async def _next_pending() -> ScrapeJob | None:
    async with _lock:
        for jid in list(_pending_order):
            j = _jobs.get(jid)
            if j and j.status == JobStatus.PENDING:
                j.status = JobStatus.IN_PROGRESS
                j.started_at = datetime.now()
                _pending_order.remove(jid)
                await _save_job(j)
                return j
        return None


# ──── startup / cleanup task ─────────────────────────────────────
async def initialize_queue() -> None:
    """백엔드 startup 시 호출 — 영속 큐 복원 + DB 초기화."""
    _ensure_db()
    loaded = await asyncio.to_thread(_load_all_jobs_sync)
    async with _lock:
        for jid, job in loaded.items():
            _jobs[jid] = job
            if job.status == JobStatus.PENDING:
                _pending_order.append(jid)
            elif job.status == JobStatus.IN_PROGRESS:
                # 백엔드 재시작 동안 in_progress 였던 것 → PENDING 으로 되돌림 (재처리)
                job.status = JobStatus.PENDING
                job.started_at = None
                _pending_order.append(jid)
                await _save_job(job)
    logger.info(
        f"[ext.queue] 영속 큐 복원: 전체 {len(loaded)}건 / pending {len(_pending_order)}건"
    )


async def cleanup_stale_jobs_loop() -> None:
    """주기적으로 stale in_progress / 만료 terminal 정리."""
    while True:
        try:
            await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
            now = datetime.now()
            to_delete: list[str] = []
            to_save: list[ScrapeJob] = []
            async with _lock:
                for jid, job in list(_jobs.items()):
                    if job.status == JobStatus.IN_PROGRESS and job.started_at:
                        elapsed = (now - job.started_at).total_seconds()
                        if elapsed > _STALE_IN_PROGRESS_SECONDS:
                            job.status = JobStatus.FAILED
                            job.last_error = f"stale_timeout ({int(elapsed)}s 동안 미응답 — 확장 SW 사망 추정)"
                            job.completed_at = now
                            to_save.append(job)
                            logger.warning(f"[ext.queue] stale → FAILED {jid}")
                    elif job.status in (JobStatus.COMPLETED, JobStatus.FAILED) and job.completed_at:
                        elapsed = (now - job.completed_at).total_seconds()
                        if elapsed > _PURGE_TERMINAL_SECONDS:
                            to_delete.append(jid)
                for jid in to_delete:
                    _jobs.pop(jid, None)
                    if jid in _pending_order:
                        _pending_order.remove(jid)
            for job in to_save:
                await _save_job(job)
            for jid in to_delete:
                await _delete_job_db(jid)
            if to_delete:
                logger.info(f"[ext.queue] {len(to_delete)}건 만료 정리")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[ext.queue] cleanup loop 예외: {e}")


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
    await _save_job(job)

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
    await _save_job(job)

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
    await _save_job(job)

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
    await _delete_job_db(job_id)
    return {"ok": True, "job_id": job_id}


# ──── 디버그/테스트용 — 큐 비우기 ────────────────────────────────
@router.post("/queue/clear")
async def clear_queue() -> dict:
    async with _lock:
        n = len(_jobs)
        ids = list(_jobs.keys())
        _jobs.clear()
        _pending_order.clear()
    for jid in ids:
        await _delete_job_db(jid)
    return {"cleared": n}
