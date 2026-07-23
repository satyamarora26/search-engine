from dataclasses import dataclass
from typing import Any
from uuid import UUID


def _require_text(
    value: str,
    field: str,
    *,
    allow_whitespace: bool = False,
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty")
    if any(
        (
            ord(char) < 32
            and (not allow_whitespace or char not in "\t\n\r")
        )
        or ord(char) == 127
        for char in value
    ):
        raise ValueError(f"{field} must not contain control characters")


class CrawlerError(Exception):
    def __init__(self, code: str, *, attempts: int = 0) -> None:
        super().__init__(code)
        self.code = code
        self.attempts = attempts


class CrawlerPolicyError(CrawlerError):
    pass


class CrawlerTransientError(CrawlerError):
    pass


class CrawlerPermanentError(CrawlerError):
    pass


class CrawlerParseError(CrawlerError):
    pass


class CrawlerDiscoveryError(CrawlerError):
    pass


@dataclass(frozen=True)
class DiscoveredItem:
    source_item_id: str | None
    title: str | None
    discovered_url: str
    canonical_url: str

    def __post_init__(self) -> None:
        if self.source_item_id is not None:
            _require_text(self.source_item_id, "source_item_id")
        if self.title is not None:
            _require_text(self.title, "title")
        _require_text(self.discovered_url, "discovered_url")
        _require_text(self.canonical_url, "canonical_url")


@dataclass(frozen=True)
class CrawlItemSnapshot:
    id: int
    position: int
    discovered_item: DiscoveredItem


@dataclass(frozen=True)
class NormalizedSeed:
    source_key: str
    canonical_url: str
    origin: str
    publication_path: str

    def __post_init__(self) -> None:
        _require_text(self.source_key, "source_key")
        _require_text(self.canonical_url, "canonical_url")
        _require_text(self.origin, "origin")
        _require_text(self.publication_path, "publication_path")


@dataclass(frozen=True)
class CrawlLimits:
    max_articles: int
    max_depth: int
    max_response_bytes: int

    def __post_init__(self) -> None:
        if type(self.max_articles) is not int or not 1 <= self.max_articles <= 500:
            raise ValueError("max_articles must be between 1 and 500")
        if type(self.max_depth) is not int or self.max_depth != 0:
            raise ValueError("max_depth must be 0")
        if type(self.max_response_bytes) is not int or self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")


@dataclass(frozen=True)
class RawPage:
    url: str
    status_code: int
    content_type: str
    body: bytes
    attempts: int

    def __post_init__(self) -> None:
        _require_text(self.url, "url")
        _require_text(self.content_type, "content_type")
        if self.status_code < 200 or self.status_code > 299:
            raise ValueError("status_code must be successful")
        if not self.body:
            raise ValueError("body must not be empty")
        if self.attempts < 1:
            raise ValueError("attempts must be positive")


@dataclass(frozen=True)
class NormalizedDocument:
    title: str
    canonical_url: str
    content: str

    def __post_init__(self) -> None:
        _require_text(self.title, "title")
        _require_text(self.canonical_url, "canonical_url")
        _require_text(self.content, "content", allow_whitespace=True)


@dataclass(frozen=True)
class DiscoveryBatch:
    items: tuple[DiscoveredItem, ...]
    frontier_locator: str
    continuation: dict[str, Any] | None
    complete: bool

    def __post_init__(self) -> None:
        _require_text(self.frontier_locator, "frontier_locator")


@dataclass(frozen=True)
class CrawlRunSnapshot:
    job_id: UUID
    source_key: str
    seed_url: str
    max_articles: int
    max_depth: int
    discovery_complete: bool
    limit_reached: bool


@dataclass(frozen=True)
class FrontierSnapshot:
    id: int
    locator: str
    depth: int
    continuation: dict[str, Any] | None


@dataclass(frozen=True)
class CrawlCounts:
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
        return self.fetch_failed + self.imported + self.skipped + self.ingestion_failed


@dataclass(frozen=True)
class CrawlItemView:
    position: int
    source_item_id: str | None
    title: str | None
    url: str
    fetch_status: str
    ingestion_status: str | None
    document_id: int | None
    error: str | None


@dataclass(frozen=True)
class DiscoveryCheckpoint:
    discovered_count: int
    discovery_complete: bool
    limit_reached: bool
