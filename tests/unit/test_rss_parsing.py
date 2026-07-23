import pytest

from app.services.crawl_types import CrawlerParseError
from app.services.rss_parsing import (
    normalize_rss_url,
    parse_article_html,
    parse_feed,
)


def test_parses_rss_items_and_embedded_content():
    body = (
        b'<rss xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        b"<channel><item>"
        b"<guid>entry-1</guid><title>Search ranking</title>"
        b"<link>https://example.com/articles/search-ranking?utm_source=rss</link>"
        b"<content:encoded><![CDATA[<p>BM25 content</p>]]></content:encoded>"
        b"</item></channel></rss>"
    )

    feed = parse_feed(body, source_url="https://example.com/feed.xml")

    assert feed.items[0].source_item_id == "entry-1"
    assert feed.items[0].canonical_url == "https://example.com/articles/search-ranking"
    assert feed.items[0].embedded_content == "<p>BM25 content</p>"


def test_parses_atom_entries_and_resolves_relative_links():
    body = (
        b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
        b"<id>tag:example.com,2026:one</id><title>Atom article</title>"
        b'<link rel="alternate" href="/articles/atom-article"/>'
        b'<content type="html"><![CDATA[<p>Atom body</p>]]></content>'
        b"</entry></feed>"
    )

    feed = parse_feed(body, source_url="https://example.com/feed.xml")

    assert feed.items[0].canonical_url == "https://example.com/articles/atom-article"
    assert feed.items[0].title == "Atom article"
    assert feed.items[0].embedded_content == "<p>Atom body</p>"


def test_normalizes_public_urls_and_article_html():
    assert normalize_rss_url(
        "HTTPS://Example.com/article?utm_medium=rss#comments"
    ) == "https://example.com/article"

    document = parse_article_html(
        """
        <html><head>
          <link rel="canonical" href="https://example.com/article?ref=feed">
          <meta property="og:title" content="Search ranking">
          <script>hidden()</script>
        </head><body><article>
          <p>BM25 balances term frequency and document frequency.</p>
          <nav>Navigation noise</nav>
        </article></body></html>
        """,
        source_url="https://example.com/article",
    )

    assert document.title == "Search ranking"
    assert document.canonical_url == "https://example.com/article"
    assert document.content == "BM25 balances term frequency and document frequency."


def test_rejects_invalid_feed_and_empty_article():
    with pytest.raises(CrawlerParseError, match="rss_invalid_feed"):
        parse_feed(b"not xml", source_url="https://example.com/feed.xml")

    with pytest.raises(CrawlerParseError, match="empty_article_content"):
        parse_article_html(
            '<html><head><link rel="canonical" href="https://example.com/a">'
            '<meta property="og:title" content="Title"></head>'
            "<body><article></article></body></html>",
            source_url="https://example.com/a",
        )
