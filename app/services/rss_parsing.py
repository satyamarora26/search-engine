from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag

from app.services.crawl_types import (
    CrawlerParseError,
    DiscoveredItem,
    NormalizedDocument,
)

_TRACKING_KEYS = {"source", "ref", "from", "feed"}


@dataclass(frozen=True)
class ParsedFeed:
    items: tuple[DiscoveredItem, ...]


def normalize_rss_url(value: str, *, base_url: str | None = None) -> str:
    absolute = urljoin(base_url, value.strip()) if base_url else value.strip()
    parsed = urlsplit(absolute)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise CrawlerParseError("rss_invalid_url")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in _TRACKING_KEYS
    ]
    return urlunsplit(
        (
            "https",
            parsed.hostname.casefold()
            + (f":{parsed.port}" if parsed.port is not None else ""),
            parsed.path or "/",
            urlencode(query),
            "",
        )
    )


def parse_feed(body: bytes, *, source_url: str) -> ParsedFeed:
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, UnicodeDecodeError):
        raise CrawlerParseError("rss_invalid_feed") from None

    entry_name = "entry" if _local_name(root.tag) == "feed" else "item"
    items = []
    for entry in root.iter():
        if _local_name(entry.tag) != entry_name:
            continue
        title = _child_text(entry, "title")
        link = _entry_link(entry)
        if not title or not link:
            continue
        try:
            canonical = normalize_rss_url(link, base_url=source_url)
        except CrawlerParseError:
            continue
        embedded_content = _child_content(entry)
        items.append(
            DiscoveredItem(
                source_item_id=_child_text(entry, "guid")
                or _child_text(entry, "id")
                or canonical,
                title=title,
                discovered_url=urljoin(source_url, link),
                canonical_url=canonical,
                embedded_content=embedded_content,
            )
        )
    return ParsedFeed(items=tuple(items))


def parse_article_html(html: str, *, source_url: str) -> NormalizedDocument:
    soup = BeautifulSoup(html, "lxml")
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical = canonical_tag.get("href") if canonical_tag else None
    if not isinstance(canonical, str) or not canonical.strip():
        raise CrawlerParseError("missing_canonical_url")
    try:
        canonical_url = normalize_rss_url(canonical, base_url=source_url)
    except CrawlerParseError:
        raise CrawlerParseError("invalid_canonical_url") from None

    meta_title = soup.find("meta", attrs={"property": "og:title"})
    title = meta_title.get("content") if meta_title is not None else None
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


def _entry_link(entry: ElementTree.Element) -> str | None:
    candidates = []
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        value = child.get("href") or (child.text or "").strip()
        if not value:
            continue
        rel = (child.get("rel") or "alternate").casefold()
        candidates.append((rel, value))
    for rel, value in candidates:
        if rel == "alternate":
            return value
    return candidates[0][1] if candidates else None


def _child_text(entry: ElementTree.Element, name: str) -> str | None:
    for child in entry:
        if _local_name(child.tag) == name:
            value = " ".join("".join(child.itertext()).split())
            if value:
                return value
    return None


def _child_content(entry: ElementTree.Element) -> str | None:
    for child in entry:
        if _local_name(child.tag) in {"encoded", "content"}:
            value = "".join(child.itertext()).strip()
            if value:
                return value
    return None


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].casefold()


def _normalized_text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=True).split())
