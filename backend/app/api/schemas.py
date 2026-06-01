from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import JobStatus

# Hard cap on copies per approval. Bumping this is fine, but stays small
# so an operator typo (e.g. "100" instead of "10") can't sink the printer.
MAX_COPIES = 10


class PublicJob(BaseModel):
    """Job view returned to the requesting user. Deliberately minimal so
    rejection reasons and internal status messages never leak."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    requester_name: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime


class AdminJob(BaseModel):
    """Full job view for the admin console."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    requester_name: str
    status: JobStatus
    status_message: str | None
    reject_reason: str | None
    retry_count: int
    copies: int
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    printed_at: datetime | None
    has_image: bool


class CreateJobResponse(BaseModel):
    id: str
    status: JobStatus


class ApproveRequest(BaseModel):
    """Optional body for the approve endpoint. Absent body / empty JSON
    both fall through to a single copy, so the older frontend (which
    POSTs no body) keeps working."""

    copies: int = Field(default=1, ge=1, le=MAX_COPIES)


class RejectRequest(BaseModel):
    reason: str


class AdminLoginRequest(BaseModel):
    password: str


class AdminMe(BaseModel):
    authenticated: bool


class AdminJobList(BaseModel):
    items: list[AdminJob]
    cursor: datetime | None
