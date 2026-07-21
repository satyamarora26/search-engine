from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_job_service
from app.schemas.jobs import JobAcceptedResponse
from app.schemas.search import SearchExplainResponse, SearchResponse
from app.services.jobs import (
    IndexJobConflictError,
    JobEnqueueError,
    JobService,
    JobStorageError,
)
from app.services.search_index import SearchIndexService
from app.services.search_index_sync import get_synchronized_search_index_service

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., alias="q"),
    ranking: Literal["bm25", "tfidf"] = "bm25",
    limit: int = Query(10, ge=1, le=50),
    search_index: SearchIndexService = Depends(
        get_synchronized_search_index_service
    ),
) -> SearchResponse:
    query = _require_non_blank_query(q)
    return search_index.search(query, ranking=ranking, limit=limit)


@router.get("/search/explain", response_model=SearchExplainResponse)
def explain(
    q: str = Query(..., alias="q"),
    document_id: int = Query(..., ge=1),
    ranking: Literal["bm25"] = "bm25",
    search_index: SearchIndexService = Depends(
        get_synchronized_search_index_service
    ),
) -> SearchExplainResponse:
    query = _require_non_blank_query(q)
    try:
        return search_index.explain(query, document_id=document_id, ranking=ranking)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/search/rebuild",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def rebuild_search_index(
    service: JobService = Depends(get_job_service),
) -> JobAcceptedResponse:
    try:
        job = service.enqueue_search_index_rebuild()
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


def _require_non_blank_query(query: str) -> str:
    stripped_query = query.strip()
    if not stripped_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank.")
    return stripped_query
