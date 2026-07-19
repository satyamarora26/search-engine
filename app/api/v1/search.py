from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.schemas.search import SearchExplainResponse, SearchResponse
from app.services.search import SearchService

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS_PATH = PROJECT_ROOT / "data" / "sample_corpus.json"

router = APIRouter(tags=["search"])
search_service = SearchService.from_json_corpus(DEFAULT_CORPUS_PATH)


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., alias="q"),
    ranking: Literal["bm25", "tfidf"] = "bm25",
    limit: int = Query(10, ge=1, le=50),
) -> SearchResponse:
    query = _require_non_blank_query(q)
    return search_service.search(query, ranking=ranking, limit=limit)


@router.get("/search/explain", response_model=SearchExplainResponse)
def explain(
    q: str = Query(..., alias="q"),
    document_id: int = Query(..., ge=1),
    ranking: Literal["bm25"] = "bm25",
) -> SearchExplainResponse:
    query = _require_non_blank_query(q)
    try:
        return search_service.explain(query, document_id=document_id, ranking=ranking)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _require_non_blank_query(query: str) -> str:
    stripped_query = query.strip()
    if not stripped_query:
        raise HTTPException(status_code=422, detail="Query cannot be blank.")
    return stripped_query
