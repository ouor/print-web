import uuid

from sqlmodel import Session, select

from app.db.models import Job, JobStatus, utcnow
from app.services.image import save_image


class DuplicateRequestError(Exception):
    """Raised when the same idempotency key is submitted twice with different content."""


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
