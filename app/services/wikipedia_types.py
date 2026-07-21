from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID


def wikipedia_article_url(title: str) -> str:
    encoded = quote(title.replace(" ", "_"), safe="()")
    return f"https://en.wikipedia.org/wiki/{encoded}"


@dataclass(frozen=True)
class WikipediaPageReference:
    page_id: int
    title: str


@dataclass(frozen=True)
class WikipediaCategoryReference:
    page_id: int
    title: str


@dataclass(frozen=True)
class WikipediaCategoryBatch:
    pages: tuple[WikipediaPageReference, ...]
    subcategories: tuple[WikipediaCategoryReference, ...]
    continuation: dict[str, Any] | None


@dataclass(frozen=True)
class FetchedWikipediaArticle:
    title: str
    canonical_url: str
    html: str
    attempts: int


@dataclass(frozen=True)
class CrawlRunSnapshot:
    job_id: UUID
    root_category: str
    max_articles: int
    max_depth: int
    discovery_complete: bool
    category_limit_reached: bool


@dataclass(frozen=True)
class FrontierSnapshot:
    id: int
    category_title: str
    depth: int
    continuation: dict[str, Any] | None


@dataclass(frozen=True)
class CrawlPageSnapshot:
    id: int
    position: int
    wikipedia_page_id: int
    title: str
    canonical_url: str


@dataclass(frozen=True)
class CrawlCounts:
    categories_visited: int
    discovered: int
    fetched: int
    imported: int
    skipped: int
    fetch_failed: int
    ingestion_failed: int

    @property
    def failed(self) -> int:
        return self.fetch_failed + self.ingestion_failed

    @property
    def terminal(self) -> int:
        return (
            self.fetch_failed
            + self.imported
            + self.skipped
            + self.ingestion_failed
        )


@dataclass(frozen=True)
class CrawlItemView:
    position: int
    wikipedia_page_id: int
    title: str
    url: str
    fetch_status: str
    ingestion_status: str | None
    document_id: int | None
    error: str | None
