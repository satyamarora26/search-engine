from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.repositories.documents import DocumentRepository
from app.schemas.search import SearchExplainResponse, SearchIndexStatus, SearchResponse
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


@router.post("/search/rebuild", response_model=SearchIndexStatus)
def rebuild_search_index(
    session: Session = Depends(get_db_session),
    search_index: SearchIndexService = Depends(get_search_index_service),
) -> SearchIndexStatus:
    documents = DocumentRepository(session).list_all_active()
    return search_index.rebuild(documents)


def _require_non_blank_query(query: str) -> str:
    stripped_query = query.strip()
    if not stripped_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank.")
    return stripped_query
