from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, SQLModel


class JobStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PRINTING = "PRINTING"
    DONE = "DONE"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.DONE, JobStatus.FAILED, JobStatus.REJECTED}
)


def utcnow() -> datetime:
    # SQLite drops tzinfo on round-trip, so store naive UTC throughout to
    # avoid mixing aware/naive datetimes when comparing.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    idempotency_key: str = Field(unique=True, index=True)
    requester_name: str
    image_path: str | None = None
    thumb_path: str | None = None
    status: JobStatus = Field(default=JobStatus.PENDING, index=True)
    status_message: str | None = None
    reject_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)
    decided_at: datetime | None = None
    printed_at: datetime | None = None
