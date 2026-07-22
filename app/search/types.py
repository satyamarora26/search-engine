from dataclasses import dataclass
from typing import Literal

SearchScope = Literal["all", "title", "content"]


@dataclass(frozen=True)
class IndexedDocument:
    id: int
    title: str
    content: str
    url: str | None = None


@dataclass(frozen=True)
class Posting:
    document_id: int
    term_frequency: int


@dataclass(frozen=True)
class SearchHit:
    document_id: int
    score: float
    matched_terms: list[str]


@dataclass(frozen=True)
class SearchPage:
    hits: list[SearchHit]
    total_results: int
