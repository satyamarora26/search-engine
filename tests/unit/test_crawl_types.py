from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from app.services.crawl_adapters import (
    get_adapter,
    register_adapter,
)
from app.services.crawl_types import (
    CrawlLimits,
    DiscoveredItem,
    DiscoveryBatch,
    NormalizedDocument,
    NormalizedSeed,
    RawPage,
)


def test_crawl_value_objects_are_immutable_and_have_stable_shapes():
    seed = NormalizedSeed(
        source_key="medium",
        canonical_url="https://medium.com/towards-data-science",
        origin="https://medium.com",
        publication_path="/towards-data-science",
    )
    limits = CrawlLimits(max_articles=25, max_depth=0, max_response_bytes=1000)
    item = DiscoveredItem(
        source_item_id="guid-1",
        title="Search ranking",
        discovered_url="https://medium.com/towards-data-science/search",
        canonical_url="https://medium.com/towards-data-science/search",
    )
    page = RawPage(
        url=item.canonical_url,
        status_code=200,
        content_type="text/html",
        body=b"<article>content</article>",
        attempts=1,
    )
    document = NormalizedDocument(
        title="Search ranking",
        canonical_url=item.canonical_url,
        content="Search ranking content.",
    )
    batch = DiscoveryBatch(
        items=(item,),
        frontier_locator="https://medium.com/feed/towards-data-science",
        continuation=None,
        complete=True,
    )

    assert seed.source_key == "medium"
    assert limits.max_articles == 25
    assert page.status_code == 200
    assert document.content.endswith("content.")
    assert batch.items == (item,)
    with pytest.raises(FrozenInstanceError):
        seed.source_key = "other"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: NormalizedSeed("medium", "", "https://medium.com", "/pub"),
        lambda: DiscoveredItem(None, "", "https://medium.com/a", "https://medium.com/a"),
        lambda: RawPage("https://medium.com/a", 200, "text/html", b"", 1),
        lambda: NormalizedDocument("Title", "https://medium.com/a", ""),
        lambda: CrawlLimits(0, 0, 100),
    ],
)
def test_crawl_value_objects_reject_empty_or_invalid_values(factory):
    with pytest.raises(ValueError):
        factory()


def test_adapter_registry_returns_registered_source_and_rejects_unknown():
    class FakeAdapter:
        source_key = "fake"

    register_adapter(FakeAdapter())

    assert get_adapter("fake").source_key == "fake"
    with pytest.raises(ValueError, match="unsupported_crawl_source"):
        get_adapter("missing")
