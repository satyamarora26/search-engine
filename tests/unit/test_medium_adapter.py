import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.crawl_types import (
    CrawlLimits,
    CrawlerDiscoveryError,
    CrawlerPolicyError,
    DiscoveredItem,
    NormalizedDocument,
    RawPage,
)
from app.services.medium_adapter import MediumAdapter

FEED = Path("tests/fixtures/medium/publication-feed.xml").read_bytes()
SITEMAP = Path("tests/fixtures/medium/publication-sitemap.xml").read_bytes()
ARTICLE = Path("tests/fixtures/medium/article.html").read_bytes()


def medium_settings(**overrides):
    values = {
        "medium_user_agent": "CrawlerTest/1.0 (test@example.com)",
        "medium_requests_per_second": 1000.0,
    }
    values.update(overrides)
    return replace(get_settings(), **values)


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return None

    async def get(self, url, *, accepted_content_type):
        self.calls.append((url, accepted_content_type))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def page(url, body, content_type, attempts=1):
    return RawPage(
        url=url,
        status_code=200,
        content_type=content_type,
        body=body,
        attempts=attempts,
    )


def adapter_fixture(responses):
    client = FakeClient(responses)
    adapter = MediumAdapter(
        settings=medium_settings(),
        client_factory=lambda: client,
    )
    return adapter, client


def test_validate_seed_accepts_publication_and_rejects_article_or_bad_hosts():
    adapter, _client = adapter_fixture({})

    seed = adapter.validate_seed("https://medium.com/towards-data-science/")

    assert seed.canonical_url == "https://medium.com/towards-data-science"
    assert seed.origin == "https://medium.com"
    assert seed.publication_path == "/towards-data-science"

    with pytest.raises(CrawlerPolicyError, match="medium_invalid_seed"):
        adapter.validate_seed("http://medium.com/towards-data-science")
    with pytest.raises(CrawlerPolicyError, match="medium_invalid_seed"):
        adapter.validate_seed("https://medium.com/p/article")
    with pytest.raises(CrawlerPolicyError, match="medium_invalid_seed"):
        adapter.validate_seed("https://example.com/towards-data-science")
    with pytest.raises(CrawlerPolicyError, match="medium_invalid_seed"):
        adapter.validate_seed("https://medium.com/towards-data-science?x=1")


def test_discovery_is_rss_first_then_sitemap_and_deduplicates_publication_urls():
    sitemap_with_archive_article = (
        SITEMAP.replace(
            b"</urlset>",
            b"<url><loc>https://medium.com/towards-data-science/three</loc></url>"
            b"</urlset>",
        )
    )
    adapter, client = adapter_fixture(
        {
            "https://medium.com/feed/towards-data-science": page(
                "https://medium.com/feed/towards-data-science",
                FEED,
                "application/rss+xml",
            ),
            "https://medium.com/sitemap.xml": page(
                "https://medium.com/sitemap.xml",
                sitemap_with_archive_article,
                "application/xml",
            ),
        }
    )
    seed = adapter.validate_seed("https://medium.com/towards-data-science")

    async def scenario():
        batches = []
        async with adapter:
            async for batch in adapter.discover(
                seed,
                CrawlLimits(max_articles=10, max_depth=0, max_response_bytes=10000),
            ):
                batches.append(batch)
        return batches

    batches = asyncio.run(scenario())

    assert [url for url, _kind in client.calls] == [
        "https://medium.com/feed/towards-data-science",
        "https://medium.com/sitemap.xml",
    ]
    assert batches[0].frontier_locator.endswith("/feed/towards-data-science")
    assert batches[0].items[0].title == "First article"
    assert batches[0].complete is False
    assert batches[1].frontier_locator.endswith("/sitemap.xml")
    assert batches[-1].complete is True


def test_discovery_respects_article_limit_and_publication_scope():
    outside_feed = FEED.replace(
        b"</channel>",
        b"<item><guid>outside</guid><title>Outside</title>"
        b"<link>https://medium.com/other-publication/outside</link></item>"
        b"</channel>",
    )
    adapter, client = adapter_fixture(
        {
            "https://medium.com/feed/towards-data-science": page(
                "https://medium.com/feed/towards-data-science",
                outside_feed,
                "application/rss+xml",
            ),
            "https://medium.com/sitemap.xml": page(
                "https://medium.com/sitemap.xml",
                SITEMAP,
                "application/xml",
            ),
        }
    )
    seed = adapter.validate_seed("https://medium.com/towards-data-science")

    async def scenario():
        items = []
        async with adapter:
            async for batch in adapter.discover(
                seed,
                CrawlLimits(max_articles=1, max_depth=0, max_response_bytes=10000),
            ):
                items.extend(batch.items)
        return items

    items = asyncio.run(scenario())

    assert len(items) == 1
    assert items[0].canonical_url.endswith("/one")
    assert [url for url, _kind in client.calls] == [
        "https://medium.com/feed/towards-data-science"
    ]


def test_discovery_uses_publication_path_declared_by_redirected_rss_feed():
    redirected_feed = FEED.replace(
        b"<title>Towards Data Science</title>",
        b"<title>Towards Data Science</title>"
        b"<link>https://medium.com/data-science?source=rss</link>",
    ).replace(
        b"https://medium.com/towards-data-science/",
        b"https://medium.com/data-science/",
    )
    adapter, client = adapter_fixture(
        {
            "https://medium.com/feed/towards-data-science": page(
                "https://medium.com/feed/towards-data-science",
                redirected_feed,
                "application/rss+xml",
            ),
        }
    )
    seed = adapter.validate_seed("https://medium.com/towards-data-science")

    async def scenario():
        async with adapter:
            async for batch in adapter.discover(
                seed,
                CrawlLimits(max_articles=1, max_depth=0, max_response_bytes=10000),
            ):
                return batch.items
        return ()

    items = asyncio.run(scenario())

    assert items[0].canonical_url == "https://medium.com/data-science/one"
    assert [url for url, _kind in client.calls] == [
        "https://medium.com/feed/towards-data-science"
    ]


def test_empty_discovery_is_a_safe_discovery_error():
    empty_feed = b"<rss><channel></channel></rss>"
    adapter, _client = adapter_fixture(
        {
            "https://medium.com/feed/towards-data-science": page(
                "https://medium.com/feed/towards-data-science",
                empty_feed,
                "application/rss+xml",
            ),
            "https://medium.com/sitemap.xml": page(
                "https://medium.com/sitemap.xml",
                b"<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'></urlset>",
                "application/xml",
            ),
        }
    )
    seed = adapter.validate_seed("https://medium.com/towards-data-science")

    async def scenario():
        async with adapter:
            async for _batch in adapter.discover(
                seed,
                CrawlLimits(max_articles=10, max_depth=0, max_response_bytes=10000),
            ):
                pass

    with pytest.raises(CrawlerDiscoveryError, match="medium_no_articles"):
        asyncio.run(scenario())


def test_fetch_and_parse_return_normalized_document():
    article_url = "https://medium.com/towards-data-science/practical-search-ranking"
    adapter, _client = adapter_fixture({article_url: page(article_url, ARTICLE, "text/html")})
    item = DiscoveredItem(
        source_item_id="article",
        title="Practical Search Ranking",
        discovered_url=article_url,
        canonical_url=article_url,
    )

    async def scenario():
        async with adapter:
            raw = await adapter.fetch(item)
            return adapter.parse(raw)

    document = asyncio.run(scenario())

    assert isinstance(document, NormalizedDocument)
    assert document.title == "Practical Search Ranking"
    assert "BM25 balances term frequency" in document.content


def test_fetch_uses_embedded_rss_content_without_an_article_request():
    adapter, client = adapter_fixture({})
    item = DiscoveredItem(
        source_item_id="article",
        title="Embedded article",
        discovered_url="https://medium.com/data-science/embedded-article",
        canonical_url="https://medium.com/data-science/embedded-article",
        embedded_content="<p>Content supplied by the publication feed.</p>",
    )

    async def scenario():
        async with adapter:
            raw = await adapter.fetch(item)
            return adapter.parse(raw)

    document = asyncio.run(scenario())

    assert document.title == "Embedded article"
    assert document.content == "Content supplied by the publication feed."
    assert client.calls == []
