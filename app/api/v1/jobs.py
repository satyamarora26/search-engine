from uuid import UUID

from fastapi import APIRouter, Depends

from app.schemas.jobs import JobStatusResponse
from app.services.jobs import JobService, get_job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{task_id}", response_model=JobStatusResponse)
def get_job_status(
    task_id: UUID,
    service: JobService = Depends(get_job_service),
) -> JobStatusResponse:
    return service.get_job_status(str(task_id))
