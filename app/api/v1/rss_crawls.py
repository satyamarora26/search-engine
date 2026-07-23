from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_rss_crawl_service
from app.schemas.jobs import JobAcceptedResponse
from app.schemas.rss_crawls import (
    CrawlItemListResponse,
    CrawlItemResponse,
    RssCrawlRequest,
)
from app.services.jobs import IndexJobConflictError, JobEnqueueError, JobStorageError
from app.services.rss_crawls import RssCrawlNotFoundError, RssCrawlService

router = APIRouter(prefix="/crawls/rss", tags=["crawls"])


@router.post(
    "",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_rss_crawl(
    payload: RssCrawlRequest,
    service: RssCrawlService = Depends(get_rss_crawl_service),
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
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        status_url=f"/api/v1/jobs/{job.id}",
    )


@router.get("/{job_id}/items", response_model=CrawlItemListResponse)
def list_rss_crawl_items(
    job_id: UUID,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: RssCrawlService = Depends(get_rss_crawl_service),
) -> CrawlItemListResponse:
    try:
        total, items = service.list_items(job_id, limit=limit, offset=offset)
    except RssCrawlNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except JobStorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return CrawlItemListResponse(
        job_id=job_id,
        total_results=total,
        limit=limit,
        offset=offset,
        items=[CrawlItemResponse.model_validate(item, from_attributes=True) for item in items],
    )
