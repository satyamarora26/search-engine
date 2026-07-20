from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel

from app.models.job import SUCCESS_STATUS, TERMINAL_STATUSES, Job


class JobProgressResponse(BaseModel):
    current: int
    total: int | None
    percentage: float | None
    message: str | None


class JobAcceptedResponse(BaseModel):
    job_id: UUID
    status: str
    status_url: str


class JobStatusResponse(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    ready: bool
    successful: bool
    progress: JobProgressResponse
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def from_job(cls, job: Job) -> Self:
        percentage = (
            None
            if job.progress_total is None
            else round(job.progress_current / job.progress_total * 100, 2)
        )
        return cls(
            job_id=job.id,
            job_type=job.job_type,
            status=job.status,
            ready=job.status in TERMINAL_STATUSES,
            successful=job.status == SUCCESS_STATUS,
            progress=JobProgressResponse(
                current=job.progress_current,
                total=job.progress_total,
                percentage=percentage,
                message=job.progress_message,
            ),
            result=job.result,
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
