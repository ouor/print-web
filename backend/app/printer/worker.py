"""Single-threaded background worker that processes APPROVED jobs.

Picks the oldest APPROVED job, marks it PRINTING, hands the blocking GDI
call to a thread executor, then settles to DONE or FAILED.
"""
from __future__ import annotations

import asyncio
import logging

from sqlmodel import Session, select

from app.core.config import settings
from app.db.engine import engine
from app.db.models import Job, JobStatus, utcnow
from app.printer.driver import PrinterError, print_image
from app.services.jobs import touch

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0
INTER_JOB_PAUSE_SECONDS = 0.5


def _claim_next_job() -> Job | None:
    """Pick the oldest APPROVED job and atomically mark it PRINTING."""
    with Session(engine) as session:
        job = session.exec(
            select(Job)
            .where(Job.status == JobStatus.APPROVED)
            .order_by(Job.decided_at, Job.created_at)
        ).first()
        if job is None:
            return None
        job.status = JobStatus.PRINTING
        touch(job)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def _mark_done(job_id: str) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = JobStatus.DONE
        job.status_message = None
        job.printed_at = utcnow()
        touch(job)
        session.add(job)
        session.commit()


def _mark_failed(job_id: str, message: str) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED
        job.status_message = message
        touch(job)
        session.add(job)
        session.commit()


def _recover_interrupted() -> int:
    """Any job left in PRINTING from a previous run is marked FAILED."""
    with Session(engine) as session:
        rows = session.exec(select(Job).where(Job.status == JobStatus.PRINTING)).all()
        for job in rows:
            job.status = JobStatus.FAILED
            job.status_message = "interrupted: server restarted mid-print"
            touch(job)
            session.add(job)
        session.commit()
        return len(rows)


async def _run_once(loop: asyncio.AbstractEventLoop) -> bool:
    job = await loop.run_in_executor(None, _claim_next_job)
    if job is None:
        return False

    log.info("printing job %s (%s) on %r", job.id, job.requester_name, settings.printer_name or "<default>")
    try:
        await loop.run_in_executor(
            None, print_image, job.image_path, settings.printer_name or None
        )
        await loop.run_in_executor(None, _mark_done, job.id)
        log.info("printed job %s", job.id)
    except PrinterError as e:
        log.exception("print failed for %s", job.id)
        await loop.run_in_executor(None, _mark_failed, job.id, str(e))
    except Exception as e:  # pragma: no cover - safety net
        log.exception("unexpected print error for %s", job.id)
        await loop.run_in_executor(None, _mark_failed, job.id, f"unexpected: {e}")
    return True


async def worker_loop(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    recovered = await loop.run_in_executor(None, _recover_interrupted)
    if recovered:
        log.warning("recovered %d interrupted job(s) to FAILED", recovered)

    while not stop_event.is_set():
        try:
            did_work = await _run_once(loop)
        except Exception:  # pragma: no cover - defensive
            log.exception("worker iteration crashed; continuing")
            did_work = False

        if did_work:
            await asyncio.sleep(INTER_JOB_PAUSE_SECONDS)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
