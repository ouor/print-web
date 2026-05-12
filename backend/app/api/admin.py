from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.schemas import (
    AdminJob,
    AdminJobList,
    AdminLoginRequest,
    AdminMe,
    RejectRequest,
)
from app.core.config import settings
from app.core.deps import is_admin, require_admin
from app.core.security import issue_session, verify_admin_password
from app.db.engine import get_session
from app.db.models import Job
from app.services.jobs import (
    InvalidTransitionError,
    approve_job,
    list_jobs_for_admin,
    reject_job,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _to_admin_job(job: Job) -> AdminJob:
    return AdminJob(
        id=job.id,
        requester_name=job.requester_name,
        status=job.status,
        status_message=job.status_message,
        reject_reason=job.reject_reason,
        created_at=job.created_at,
        updated_at=job.updated_at,
        decided_at=job.decided_at,
        printed_at=job.printed_at,
        # Trust the column: retention sweep nulls image_path when it
        # deletes the file, so a non-null value is authoritative without
        # an extra stat per row.
        has_image=bool(job.image_path),
    )


@router.post("/login", response_model=AdminMe)
def login(payload: AdminLoginRequest, response: Response) -> AdminMe:
    if not verify_admin_password(payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password")

    response.set_cookie(
        key=settings.session_cookie_name,
        value=issue_session(),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_secure,
        path="/",
    )
    return AdminMe(authenticated=True)


@router.post("/logout", response_model=AdminMe)
def logout(response: Response) -> AdminMe:
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return AdminMe(authenticated=False)


@router.get("/me", response_model=AdminMe)
def me(request: Request) -> AdminMe:
    return AdminMe(authenticated=is_admin(request))


@router.get("/jobs", response_model=AdminJobList, dependencies=[Depends(require_admin)])
def list_jobs(
    since: datetime | None = None,
    session: Session = Depends(get_session),
) -> AdminJobList:
    jobs = list_jobs_for_admin(session, since=since)
    cursor = max((j.updated_at for j in jobs), default=since)
    return AdminJobList(items=[_to_admin_job(j) for j in jobs], cursor=cursor)


@router.post(
    "/jobs/{job_id}/approve",
    response_model=AdminJob,
    dependencies=[Depends(require_admin)],
)
def approve(
    job_id: str,
    session: Session = Depends(get_session),
) -> AdminJob:
    try:
        job = approve_job(session, job_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _to_admin_job(job)


@router.post(
    "/jobs/{job_id}/reject",
    response_model=AdminJob,
    dependencies=[Depends(require_admin)],
)
def reject(
    job_id: str,
    payload: RejectRequest,
    session: Session = Depends(get_session),
) -> AdminJob:
    try:
        job = reject_job(session, job_id, payload.reason)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _to_admin_job(job)


def _serve_stored_file(session: Session, job_id: str, attr: str) -> FileResponse:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    stored = getattr(job, attr)
    if not stored:
        raise HTTPException(status_code=404, detail="file not stored")
    path = Path(stored)
    if not path.exists():
        raise HTTPException(status_code=404, detail="file missing")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/jobs/{job_id}/thumb", dependencies=[Depends(require_admin)])
def job_thumb(job_id: str, session: Session = Depends(get_session)) -> FileResponse:
    return _serve_stored_file(session, job_id, "thumb_path")


@router.get("/jobs/{job_id}/image", dependencies=[Depends(require_admin)])
def job_image(job_id: str, session: Session = Depends(get_session)) -> FileResponse:
    return _serve_stored_file(session, job_id, "image_path")
