"""Per-printer background workers that drain APPROVED jobs.

One worker_loop task per configured printer. Each worker independently
polls for APPROVED jobs, but the claim itself is serialized through a
shared asyncio.Lock so two workers can't grab the same row. After
claiming, the worker runs GDI + spool tracking on its own printer in a
thread executor and settles the job to DONE or FAILED.

This gives "route to whichever printer is idle" for free: an idle
worker is one whose loop just returned to polling, so it'll grab the
next claim while busy workers are still mid-print.
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


def _claim_next_job(printer_name: str) -> Job | None:
    """Pick the oldest APPROVED job, mark it PRINTING, and stamp printer_name.

    Caller MUST hold the shared claim lock. The SQLModel session uses
    SQLite's default isolation, which would otherwise let two workers
    SELECT the same row before either UPDATEs.
    """
    with Session(engine) as session:
        job = session.exec(
            select(Job)
            .where(Job.status == JobStatus.APPROVED)
            .order_by(Job.decided_at, Job.created_at)
        ).first()
        if job is None:
            return None
        job.status = JobStatus.PRINTING
        job.printer_name = printer_name
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


def recover_interrupted() -> int:
    """Mark every PRINTING job from a previous run as FAILED.

    Called once at startup by app.main before workers spawn. Public
    (no leading underscore) because main now owns the call site.
    """
    with Session(engine) as session:
        rows = session.exec(select(Job).where(Job.status == JobStatus.PRINTING)).all()
        for job in rows:
            job.status = JobStatus.FAILED
            job.status_message = "interrupted: server restarted mid-print"
            touch(job)
            session.add(job)
        session.commit()
        return len(rows)


async def _run_once(
    loop: asyncio.AbstractEventLoop,
    printer_name: str,
    claim_lock: asyncio.Lock,
) -> bool:
    async with claim_lock:
        job = await loop.run_in_executor(None, _claim_next_job, printer_name)
    if job is None:
        return False

    # Defensive clamp — DB column has a default of 1 but a hand-edited row
    # could still be 0/negative.
    total = max(1, int(job.copies or 1))
    log.info(
        "printing job %s (%s) on %r [retry=%d, copies=%d]",
        job.id, job.requester_name, printer_name, job.retry_count, total,
    )
    # Per-attempt + per-copy unique doc name so the spool tracker can lock
    # onto exactly this submission in EnumJobs even if the same job was
    # printed before or queues another copy right after.
    for i in range(total):
        copy_idx = i + 1
        doc_name = f"print-web:{job.id}:{job.retry_count}:{copy_idx}/{total}"
        try:
            # Bind doc_name as a default arg to avoid the classic
            # late-binding closure bug when looping.
            await loop.run_in_executor(
                None,
                lambda d=doc_name: print_image(
                    job.image_path,
                    printer_name,
                    spool_doc_name=d,
                    spool_timeout_seconds=settings.print_spool_timeout_seconds,
                ),
            )
            log.info(
                "printed copy %d/%d of job %s on %s",
                copy_idx, total, job.id, printer_name,
            )
        except PrinterError as e:
            log.exception(
                "print failed for %s on %s (copy %d/%d)",
                job.id, printer_name, copy_idx, total,
            )
            await loop.run_in_executor(
                None,
                _mark_failed,
                job.id,
                f"{printer_name} {copy_idx}/{total}장: {e}",
            )
            # Stop the rest of the run: continuing after a confirmed
            # failure would print the wrong total and confuse the admin.
            return True
        except Exception as e:  # pragma: no cover - safety net
            log.exception(
                "unexpected print error for %s on %s (copy %d/%d)",
                job.id, printer_name, copy_idx, total,
            )
            await loop.run_in_executor(
                None,
                _mark_failed,
                job.id,
                f"{printer_name} {copy_idx}/{total}장: unexpected: {e}",
            )
            return True

    await loop.run_in_executor(None, _mark_done, job.id)
    log.info("printed job %s on %s (%d copies)", job.id, printer_name, total)
    return True


async def worker_loop(
    stop_event: asyncio.Event,
    printer_name: str,
    claim_lock: asyncio.Lock,
) -> None:
    """One worker per printer. Polls, claims (under lock), prints, repeats."""
    loop = asyncio.get_running_loop()

    while not stop_event.is_set():
        try:
            did_work = await _run_once(loop, printer_name, claim_lock)
        except Exception:  # pragma: no cover - defensive
            log.exception("worker[%s] iteration crashed; continuing", printer_name)
            did_work = False

        if did_work:
            await asyncio.sleep(INTER_JOB_PAUSE_SECONDS)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
