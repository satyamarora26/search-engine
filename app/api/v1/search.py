from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.jobs import JobAcceptedResponse
from app.schemas.search import SearchExplainResponse, SearchResponse
from app.services.jobs import JobEnqueueError, JobService, get_job_service
from app.services.search_index import SearchIndexService, get_search_index_service

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., alias="q"),
    ranking: Literal["bm25", "tfidf"] = "bm25",
    limit: int = Query(10, ge=1, le=50),
    search_index: SearchIndexService = Depends(get_search_index_service),
) -> SearchResponse:
    query = _require_non_blank_query(q)
    return search_index.search(query, ranking=ranking, limit=limit)


@router.get("/search/explain", response_model=SearchExplainResponse)
def explain(
    q: str = Query(..., alias="q"),
    document_id: int = Query(..., ge=1),
    ranking: Literal["bm25"] = "bm25",
    search_index: SearchIndexService = Depends(get_search_index_service),
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
        task_id = service.enqueue_search_index_rebuild()
    except JobEnqueueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JobAcceptedResponse(
        task_id=task_id,
        status="PENDING",
        status_url=f"/api/v1/jobs/{task_id}",
    )


def _require_non_blank_query(query: str) -> str:
    stripped_query = query.strip()
    if not stripped_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank.")
    return stripped_query
