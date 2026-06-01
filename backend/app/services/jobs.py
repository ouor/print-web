import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.db.models import Job, JobStatus, utcnow
from app.services.image import save_image


class InvalidTransitionError(Exception):
    pass


def create_job(
    session: Session,
    *,
    requester_name: str,
    idempotency_key: str,
    image_bytes: bytes,
) -> Job:
    existing = session.exec(
        select(Job).where(Job.idempotency_key == idempotency_key)
    ).first()
    if existing is not None:
        return existing

    job_id = uuid.uuid4().hex
    image_path, thumb_path = save_image(image_bytes, job_id)

    job = Job(
        id=job_id,
        idempotency_key=idempotency_key,
        requester_name=requester_name.strip(),
        image_path=str(image_path),
        thumb_path=str(thumb_path),
        status=JobStatus.PENDING,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_job(session: Session, job_id: str) -> Job | None:
    return session.get(Job, job_id)


def touch(job: Job) -> None:
    job.updated_at = utcnow()


def list_jobs_for_admin(
    session: Session,
    *,
    since: datetime | None,
    limit: int = 200,
) -> list[Job]:
    stmt = select(Job)
    if since is not None:
        stmt = stmt.where(Job.updated_at > since)
    stmt = stmt.order_by(Job.updated_at.desc()).limit(limit)  # type: ignore[union-attr]
    return list(session.exec(stmt))


def _decide_pending(
    session: Session,
    job_id: str,
    *,
    new_status: JobStatus,
    reject_reason: str | None = None,
    copies: int | None = None,
) -> Job:
    """Move a PENDING job to APPROVED or REJECTED. Raises if no such job
    or if the job has already left PENDING."""
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(job_id)
    if job.status != JobStatus.PENDING:
        raise InvalidTransitionError(
            f"cannot transition job in status {job.status} to {new_status}"
        )
    now = utcnow()
    job.status = new_status
    job.decided_at = now
    job.updated_at = now
    if reject_reason is not None:
        job.reject_reason = reject_reason.strip() or None
    if copies is not None:
        # API layer already bounds this; clamp defensively so a direct
        # service call can't queue a runaway print job.
        job.copies = max(1, int(copies))
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def approve_job(session: Session, job_id: str, *, copies: int = 1) -> Job:
    return _decide_pending(
        session, job_id, new_status=JobStatus.APPROVED, copies=copies
    )


def reject_job(session: Session, job_id: str, reason: str) -> Job:
    return _decide_pending(
        session, job_id, new_status=JobStatus.REJECTED, reject_reason=reason
    )


def retry_job(session: Session, job_id: str) -> Job:
    """Send a FAILED job back to APPROVED so the worker picks it up again.

    Bumps retry_count and clears the previous failure message. Only FAILED
    is allowed — DONE/REJECTED/PENDING/APPROVED/PRINTING all raise.
    """
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(job_id)
    if job.status != JobStatus.FAILED:
        raise InvalidTransitionError(
            f"cannot retry job in status {job.status}; only FAILED is retryable"
        )
    if not job.image_path:
        # Retention sweep nulled the file out — nothing to reprint.
        raise InvalidTransitionError("image file no longer stored; ask the requester to resubmit")

    now = utcnow()
    job.status = JobStatus.APPROVED
    job.status_message = None
    job.retry_count += 1
    job.decided_at = now
    job.printed_at = None
    job.updated_at = now
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
