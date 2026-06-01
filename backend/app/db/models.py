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
    # Number of admin-initiated retries. 0 on first attempt; bumped each
    # time a FAILED job is sent back to APPROVED via the retry endpoint.
    retry_count: int = Field(default=0)
    # Number of copies the admin requested at approval time. The worker
    # prints the same image this many times back-to-back before releasing
    # the printer, so the requester's whole batch always comes out before
    # the next job's pages. Bounded 1..MAX_COPIES at the API layer.
    copies: int = Field(default=1)
    # The printer that picked this job up. Set when the worker atomically
    # claims an APPROVED job; null while pending. Useful for spotting
    # patterns like "all FAILED jobs came from printer X" without piping
    # logs.
    printer_name: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)
    decided_at: datetime | None = None
    printed_at: datetime | None = None
