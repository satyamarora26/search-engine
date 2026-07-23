import asyncio
from dataclasses import replace

import pytest

from app.core.config import get_settings
from app.services.crawl_types import (
    CrawlLimits,
    CrawlerDiscoveryError,
    CrawlerPolicyError,
    DiscoveredItem,
    RawPage,
)
from app.services.rss_adapter import RssAdapter


def rss_settings(**overrides):
    values = {
        "rss_user_agent": "RssCrawlerTest/1.0 (test@example.com)",
        "rss_requests_per_second": 1000.0,
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
    adapter = RssAdapter(
        settings=rss_settings(),
        client_factory=lambda: client,
    )
    return adapter, client


def test_validates_https_feed_and_rejects_credentials_or_non_https():
    adapter, _client = adapter_fixture({})

    seed = adapter.validate_seed("https://example.com/feed.xml?format=rss")

    assert seed.canonical_url == "https://example.com/feed.xml?format=rss"
    assert seed.origin == "https://example.com"

    with pytest.raises(CrawlerPolicyError, match="rss_invalid_seed"):
        adapter.validate_seed("http://example.com/feed.xml")
    with pytest.raises(CrawlerPolicyError, match="rss_invalid_seed"):
        adapter.validate_seed("https://user:pass@example.com/feed.xml")
    fragment_seed = adapter.validate_seed("https://example.com/feed.xml#latest")
    assert fragment_seed.canonical_url == "https://example.com/feed.xml"


def test_discovery_is_bounded_same_host_and_rss_first():
    feed = (
        b"<rss><channel><item><guid>one</guid><title>One</title>"
        b"<link>https://example.com/one</link></item>"
        b"<item><guid>outside</guid><title>Outside</title>"
        b"<link>https://other.example.com/outside</link></item>"
        b"<item><guid>two</guid><title>Two</title>"
        b"<link>https://example.com/two</link></item>"
        b"</channel></rss>"
    )
    adapter, client = adapter_fixture(
        {"https://example.com/feed.xml": page(
            "https://example.com/feed.xml", feed, "application/rss+xml"
        )}
    )
    seed = adapter.validate_seed("https://example.com/feed.xml")

    async def scenario():
        batches = []
        async with adapter:
            async for batch in adapter.discover(
                seed,
                CrawlLimits(max_articles=1, max_depth=0, max_response_bytes=10000),
            ):
                batches.append(batch)
        return batches

    batches = asyncio.run(scenario())

    assert [item.canonical_url for item in batches[0].items] == [
        "https://example.com/one"
    ]
    assert batches[0].complete is True
    assert client.calls == [("https://example.com/feed.xml", "xml")]


def test_fetch_uses_embedded_content_before_article_http():
    adapter, client = adapter_fixture({})
    item = DiscoveredItem(
        source_item_id="one",
        title="One",
        discovered_url="https://example.com/one",
        canonical_url="https://example.com/one",
        embedded_content="<p>Embedded body</p>",
    )

    async def scenario():
        async with adapter:
            return adapter.parse(await adapter.fetch(item))

    document = asyncio.run(scenario())

    assert document.title == "One"
    assert document.content == "Embedded body"
    assert client.calls == []


def test_empty_feed_is_a_safe_discovery_error():
    adapter, _client = adapter_fixture(
        {"https://example.com/feed.xml": page(
            "https://example.com/feed.xml",
            b"<rss><channel /></rss>",
            "application/rss+xml",
        )}
    )
    seed = adapter.validate_seed("https://example.com/feed.xml")

    async def scenario():
        async with adapter:
            async for _batch in adapter.discover(
                seed,
                CrawlLimits(max_articles=10, max_depth=0, max_response_bytes=10000),
            ):
                pass

    with pytest.raises(CrawlerDiscoveryError, match="rss_no_articles"):
        asyncio.run(scenario())
