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


def approve_job(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(job_id)
    if job.status != JobStatus.PENDING:
        raise InvalidTransitionError(f"cannot approve job in status {job.status}")
    now = utcnow()
    job.status = JobStatus.APPROVED
    job.decided_at = now
    job.updated_at = now
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def reject_job(session: Session, job_id: str, reason: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(job_id)
    if job.status != JobStatus.PENDING:
        raise InvalidTransitionError(f"cannot reject job in status {job.status}")
    now = utcnow()
    job.status = JobStatus.REJECTED
    job.reject_reason = reason.strip() or None
    job.decided_at = now
    job.updated_at = now
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
