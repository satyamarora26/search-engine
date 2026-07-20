from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_job_service
from app.schemas.jobs import JobStatusResponse
from app.services.jobs import JobNotFoundError, JobService, JobStorageError

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: UUID,
    service: JobService = Depends(get_job_service),
) -> JobStatusResponse:
    try:
        job = service.get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except JobStorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JobStatusResponse.from_job(job)
