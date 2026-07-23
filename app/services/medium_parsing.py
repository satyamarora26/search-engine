from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from app.services.crawl_types import (
    CrawlerParseError,
    DiscoveredItem,
    NormalizedDocument,
)

_TRACKING_KEYS = {"source", "ref", "sk", "from"}


def normalize_medium_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise CrawlerParseError("medium_invalid_url")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in _TRACKING_KEYS
    ]
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.hostname.casefold()
            + (f":{parsed.port}" if parsed.port is not None else ""),
            parsed.path or "/",
            urlencode(query),
            "",
        )
    )


def parse_article_html(html: str, *, source_url: str) -> NormalizedDocument:
    soup = BeautifulSoup(html, "lxml")
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical = canonical_tag.get("href") if canonical_tag else None
    if not isinstance(canonical, str) or not canonical.strip():
        raise CrawlerParseError("missing_canonical_url")
    try:
        canonical_url = normalize_medium_url(canonical)
    except CrawlerParseError:
        raise CrawlerParseError("invalid_canonical_url") from None

    title = None
    meta_title = soup.find("meta", attrs={"property": "og:title"})
    if meta_title is not None:
        title = meta_title.get("content")
    if not isinstance(title, str) or not title.strip():
        title_tag = soup.find("title")
        title = title_tag.get_text(" ", strip=True) if title_tag else None
    if not title:
        raise CrawlerParseError("missing_article_title")

    body = soup.find("article") or soup.find("main") or soup.body
    if body is None:
        raise CrawlerParseError("missing_article_body")
    for selector in ("script", "style", "nav", "aside", "form", "figure"):
        for node in body.select(selector):
            node.decompose()
    chunks = []
    for node in body.find_all(("h1", "h2", "h3", "p", "li")):
        text = _normalized_text(node)
        if text:
            chunks.append(text)
    if not chunks:
        text = _normalized_text(body)
        if text:
            chunks.append(text)
    content = "\n\n".join(chunks)
    if not content:
        raise CrawlerParseError("empty_article_content")

    return NormalizedDocument(
        title=" ".join(title.split()),
        canonical_url=canonical_url,
        content=content,
    )


def parse_rss_feed(body: bytes) -> tuple[DiscoveredItem, ...]:
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, UnicodeDecodeError):
        raise CrawlerParseError("medium_invalid_rss") from None

    items = []
    for element in root.iter():
        if _local_name(element.tag) != "item":
            continue
        values = {
            _local_name(child.tag): (child.text or "").strip()
            for child in element
        }
        link = values.get("link")
        title = values.get("title")
        if not link or not title:
            continue
        try:
            canonical = normalize_medium_url(link)
        except CrawlerParseError:
            continue
        items.append(
            DiscoveredItem(
                source_item_id=values.get("guid") or canonical,
                title=title,
                discovered_url=link,
                canonical_url=canonical,
            )
        )
    return tuple(items)


def parse_sitemap(body: bytes) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, UnicodeDecodeError):
        raise CrawlerParseError("medium_invalid_sitemap") from None

    local_name = _local_name(root.tag)
    values = tuple(
        (element.text or "").strip()
        for element in root.iter()
        if _local_name(element.tag) == "loc" and element.text
    )
    if local_name == "sitemapindex":
        return (), values
    if local_name == "urlset":
        return values, ()
    raise CrawlerParseError("medium_invalid_sitemap")


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].casefold()


def _normalized_text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=True).split())
