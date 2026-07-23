from datetime import date
from typing import Literal

from pydantic import BaseModel

SearchScope = Literal["all", "title", "content"]


class SearchResult(BaseModel):
    document_id: int
    title: str
    url: str | None
    score: float
    snippet: str
    matched_terms: list[str]


class SearchResponse(BaseModel):
    query: str
    ranking: str
    total_results: int
    index_version: str
    limit: int
    offset: int
    scope: SearchScope
    exact_phrase: bool
    source: str | None
    created_from: date | None
    created_to: date | None
    results: list[SearchResult]


class SearchExplainTerm(BaseModel):
    term: str
    term_frequency: int
    document_frequency: int
    idf: float
    contribution: float


class SearchExplainResponse(BaseModel):
    query: str
    ranking: str
    document_id: int
    final_score: float
    terms: list[SearchExplainTerm]


class SearchIndexStatus(BaseModel):
    index_version: str
    document_count: int
