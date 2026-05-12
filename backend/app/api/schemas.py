from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import JobStatus


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
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None
    printed_at: datetime | None
    has_image: bool


class CreateJobResponse(BaseModel):
    id: str
    status: JobStatus


class RejectRequest(BaseModel):
    reason: str


class AdminLoginRequest(BaseModel):
    password: str


class AdminMe(BaseModel):
    authenticated: bool


class AdminJobList(BaseModel):
    items: list[AdminJob]
    cursor: datetime | None
