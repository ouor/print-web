"""Periodic cleanup of stored images for terminal jobs older than RETENTION_DAYS.

DB rows are kept for audit; only the image/thumb files are removed and the
paths nulled out.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlmodel import Session, or_, select

from app.core.config import settings
from app.db.engine import engine
from app.db.models import TERMINAL_STATUSES, Job, JobStatus, utcnow
from app.services.image import delete_image_files

log = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 24 * 3600


def _cutoff() -> datetime:
    return utcnow() - timedelta(days=settings.retention_days)


def _terminal_reference_time(job: Job) -> datetime:
    return job.printed_at or job.decided_at or job.updated_at


def sweep_once() -> int:
    """Delete files for terminal jobs past the retention cutoff. Returns count purged."""
    cutoff = _cutoff()
    purged = 0
    with Session(engine) as session:
        candidates = session.exec(
            select(Job).where(
                Job.status.in_([s.value for s in TERMINAL_STATUSES]),  # type: ignore[attr-defined]
                or_(Job.image_path.is_not(None), Job.thumb_path.is_not(None)),  # type: ignore[union-attr]
            )
        ).all()
        for job in candidates:
            if _terminal_reference_time(job) > cutoff:
                continue
            delete_image_files(job.image_path, job.thumb_path)
            job.image_path = None
            job.thumb_path = None
            job.updated_at = utcnow()
            session.add(job)
            purged += 1
        if purged:
            session.commit()
    return purged


async def retention_loop(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    while not stop_event.is_set():
        try:
            n = await loop.run_in_executor(None, sweep_once)
            if n:
                log.info("retention sweep purged %d job image(s)", n)
        except Exception:  # pragma: no cover - defensive
            log.exception("retention sweep failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=SWEEP_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
