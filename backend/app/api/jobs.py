from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlmodel import Session

from app.api.schemas import CreateJobResponse, PublicJob
from app.core.config import settings
from app.db.engine import get_session
from app.services.image import InvalidImageError
from app.services.jobs import create_job, get_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

MAX_NAME_LEN = 50


@router.post("", response_model=CreateJobResponse, status_code=status.HTTP_201_CREATED)
async def submit_job(
    requester_name: str = Form(..., min_length=1, max_length=MAX_NAME_LEN),
    idempotency_key: str = Form(..., min_length=8, max_length=128),
    image: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> CreateJobResponse:
    name = requester_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="requester_name must not be blank")

    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=422, detail="empty image upload")
    if len(raw) > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="image exceeds size limit")

    try:
        job = create_job(
            session,
            requester_name=name,
            idempotency_key=idempotency_key,
            image_bytes=raw,
        )
    except InvalidImageError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return CreateJobResponse(id=job.id, status=job.status)


@router.get("/{job_id}", response_model=PublicJob)
def fetch_job(
    job_id: str,
    session: Session = Depends(get_session),
) -> PublicJob:
    job = get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return PublicJob.model_validate(job)
