from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class DiscoveredItem:
    source_item_id: str | None
    title: str | None
    discovered_url: str
    canonical_url: str


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
