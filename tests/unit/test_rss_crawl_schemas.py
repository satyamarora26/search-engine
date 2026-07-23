from pydantic import ValidationError

from app.schemas.rss_crawls import RssCrawlRequest


def test_request_normalizes_feed_url_and_uses_bounded_defaults():
    request = RssCrawlRequest(feed_url="https://example.com/feed.xml#latest")

    assert request.feed_url == "https://example.com/feed.xml"
    assert request.max_articles == 100
    assert request.max_depth == 0


def test_request_rejects_unsafe_feed_urls_and_unknown_fields():
    for payload in (
        {"feed_url": "http://example.com/feed.xml"},
        {"feed_url": "https://user:pass@example.com/feed.xml"},
        {"feed_url": "https://example.com/feed.xml", "max_depth": 1},
        {"feed_url": "https://example.com/feed.xml", "unknown": True},
    ):
        try:
            RssCrawlRequest.model_validate(payload)
        except ValidationError:
            continue
        raise AssertionError(f"payload should be rejected: {payload}")
