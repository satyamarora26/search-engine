from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_medium_crawl_service
from app.schemas.jobs import JobAcceptedResponse
from app.schemas.medium_crawls import (
    CrawlItemListResponse,
    CrawlItemResponse,
    MediumCrawlRequest,
)
from app.services.jobs import (
    IndexJobConflictError,
    JobEnqueueError,
    JobStorageError,
)
from app.services.medium_crawls import (
    MediumCrawlNotFoundError,
    MediumCrawlService,
)

router = APIRouter(prefix="/crawls/medium", tags=["crawls"])


@router.post(
    "",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_medium_crawl(
    payload: MediumCrawlRequest,
    service: MediumCrawlService = Depends(get_medium_crawl_service),
) -> JobAcceptedResponse:
    try:
        job = service.enqueue_crawl(payload)
    except IndexJobConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(error),
                "active_job_id": str(error.active_job.id),
                "status_url": f"/api/v1/jobs/{error.active_job.id}",
            },
        ) from error
    except (JobEnqueueError, JobStorageError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    return JobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        status_url=f"/api/v1/jobs/{job.id}",
    )


@router.get(
    "/{job_id}/items",
    response_model=CrawlItemListResponse,
)
def list_medium_crawl_items(
    job_id: UUID,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: MediumCrawlService = Depends(get_medium_crawl_service),
) -> CrawlItemListResponse:
    try:
        total, items = service.list_items(job_id, limit=limit, offset=offset)
    except MediumCrawlNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except JobStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    return CrawlItemListResponse(
        job_id=job_id,
        total_results=total,
        limit=limit,
        offset=offset,
        items=[
            CrawlItemResponse.model_validate(item, from_attributes=True)
            for item in items
        ],
    )
