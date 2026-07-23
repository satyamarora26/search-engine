from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.services.crawl_types import (
    CrawlLimits,
    DiscoveryBatch,
    DiscoveredItem,
    NormalizedDocument,
    NormalizedSeed,
    RawPage,
)


@runtime_checkable
class CrawlAdapter(Protocol):
    source_key: str

    def validate_seed(self, seed_url: str) -> NormalizedSeed: ...

    def discover(
        self,
        seed: NormalizedSeed,
        limits: CrawlLimits,
    ) -> AsyncIterator[DiscoveryBatch]: ...

    async def fetch(self, discovered_item: DiscoveredItem) -> RawPage: ...

    def parse(self, raw_page: RawPage) -> NormalizedDocument: ...


_ADAPTERS: dict[str, CrawlAdapter] = {}


def register_adapter(adapter: CrawlAdapter) -> CrawlAdapter:
    source_key = getattr(adapter, "source_key", None)
    if not isinstance(source_key, str) or not source_key.strip():
        raise ValueError("adapter source_key must not be empty")
    _ADAPTERS[source_key] = adapter
    return adapter


def get_adapter(source_key: str) -> CrawlAdapter:
    try:
        return _ADAPTERS[source_key]
    except KeyError:
        raise ValueError("unsupported_crawl_source") from None
