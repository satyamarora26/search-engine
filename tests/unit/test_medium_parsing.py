from pathlib import Path

import pytest

from app.services.crawl_types import CrawlerParseError, DiscoveredItem
from app.services.medium_parsing import (
    normalize_medium_url,
    parse_article_html,
    parse_rss_feed,
    parse_rss_publication_path,
    parse_sitemap,
)

ARTICLE_FIXTURE = Path("tests/fixtures/medium/article.html")
RSS_FIXTURE = Path("tests/fixtures/medium/publication-feed.xml")
SITEMAP_FIXTURE = Path("tests/fixtures/medium/publication-sitemap.xml")


def test_normalizes_medium_urls_without_fragments_or_tracking_parameters():
    assert normalize_medium_url(
        "HTTPS://Medium.com/Towards-Data-Science/article?utm_source=x#comments"
    ) == "https://medium.com/Towards-Data-Science/article"


def test_parses_article_title_canonical_url_and_clean_content():
    document = parse_article_html(
        ARTICLE_FIXTURE.read_text(encoding="utf-8"),
        source_url="https://medium.com/towards-data-science/article?source=feed",
    )

    assert document.title == "Practical Search Ranking"
    assert document.canonical_url == (
        "https://medium.com/towards-data-science/practical-search-ranking"
    )
    assert "BM25 balances term frequency" in document.content
    assert "Navigation noise" not in document.content
    assert "hidden script" not in document.content


@pytest.mark.parametrize(
    ("html", "code"),
    [
        ("<html><body><article>Text only</article></body></html>", "missing_canonical_url"),
        (
            '<html><head><link rel="canonical" href="https://medium.com/a"></head>'
            "<body><article>Text only</article></body></html>",
            "missing_article_title",
        ),
        (
            '<html><head><link rel="canonical" href="https://medium.com/a">'
            '<meta property="og:title" content="Title"></head>'
            "<body><article></article></body></html>",
            "empty_article_content",
        ),
    ],
)
def test_rejects_missing_or_empty_article_fields(html, code):
    with pytest.raises(CrawlerParseError) as caught:
        parse_article_html(html, source_url="https://medium.com/a")

    assert caught.value.code == code
    assert html not in str(caught.value)


def test_parses_rss_items_in_feed_order_with_stable_source_ids():
    items = parse_rss_feed(RSS_FIXTURE.read_bytes())

    assert items == (
        DiscoveredItem(
            source_item_id="https://medium.com/towards-data-science/one",
            title="First article",
            discovered_url="https://medium.com/towards-data-science/one",
            canonical_url="https://medium.com/towards-data-science/one",
        ),
        DiscoveredItem(
            source_item_id="guid-two",
            title="Second article",
            discovered_url="https://medium.com/towards-data-science/two?utm_medium=rss",
            canonical_url="https://medium.com/towards-data-science/two",
        ),
    )


def test_parses_publication_path_from_rss_channel_link():
    body = RSS_FIXTURE.read_bytes().replace(
        b"<title>Towards Data Science</title>",
        b"<title>Towards Data Science</title>"
        b"<link>https://medium.com/data-science?source=rss</link>",
    )

    assert parse_rss_publication_path(body) == "/data-science"


def test_preserves_full_content_encoded_rss_entry():
    body = (
        b'<rss xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        b"<channel><item>"
        b"<title>Full article</title>"
        b"<link>https://medium.com/data-science/full-article</link>"
        b"<content:encoded><![CDATA[<p>Full body</p>]]></content:encoded>"
        b"</item></channel></rss>"
    )

    items = parse_rss_feed(body)

    assert items[0].embedded_content == "<p>Full body</p>"


def test_parses_sitemap_urls_and_sitemap_indexes():
    urls, nested = parse_sitemap(SITEMAP_FIXTURE.read_bytes())

    assert urls == (
        "https://medium.com/towards-data-science/one",
        "https://medium.com/towards-data-science/two",
    )
    assert nested == ()

    index_urls, nested_urls = parse_sitemap(
        b"<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>"
        b"<sitemap><loc>https://medium.com/sitemap-1.xml</loc></sitemap>"
        b"</sitemapindex>"
    )
    assert index_urls == ()
    assert nested_urls == ("https://medium.com/sitemap-1.xml",)
