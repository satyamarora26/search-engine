from collections.abc import AsyncIterator, Callable
from html import escape
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import Settings, get_settings
from app.services.crawl_adapters import register_adapter
from app.services.crawl_types import (
    CrawlLimits,
    CrawlerDiscoveryError,
    CrawlerParseError,
    CrawlerPolicyError,
    DiscoveredItem,
    DiscoveryBatch,
    NormalizedDocument,
    NormalizedSeed,
    RawPage,
)
from app.services.rss_http import RssHttpClient, create_rss_http_client
from app.services.rss_parsing import parse_article_html, parse_feed


def normalize_rss_feed_url(seed_url: str) -> NormalizedSeed:
    try:
        parsed = httpx.URL(seed_url.strip())
    except httpx.InvalidURL:
        raise CrawlerPolicyError("rss_invalid_seed") from None
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.host
        or parsed.username not in (None, "")
        or parsed.password not in (None, "")
    ):
        raise CrawlerPolicyError("rss_invalid_seed")
    canonical = urlunsplit(
        (
            "https",
            parsed.host.casefold()
            + (f":{parsed.port}" if parsed.port is not None else ""),
            parsed.path or "/",
            parsed.query.decode("utf-8"),
            "",
        )
    )
    return NormalizedSeed(
        source_key="rss",
        canonical_url=canonical,
        origin=f"https://{parsed.host.casefold()}"
        + (f":{parsed.port}" if parsed.port is not None else ""),
        publication_path=parsed.path or "/",
    )


class RssAdapter:
    source_key = "rss"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client_factory: Callable[[], RssHttpClient] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client_factory = client_factory or (
            lambda: create_rss_http_client(self.settings)
        )
        self._client: RssHttpClient | None = None
        self._entered_client: object | None = None

    async def __aenter__(self) -> "RssAdapter":
        client = self.client_factory()
        self._client = client
        enter = getattr(client, "__aenter__", None)
        self._entered_client = await enter() if enter is not None else client
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        client = self._client
        exit_method = getattr(client, "__aexit__", None)
        if exit_method is not None:
            await exit_method(*exc_info)
        self._client = None
        self._entered_client = None

    def validate_seed(self, seed_url: str) -> NormalizedSeed:
        return normalize_rss_feed_url(seed_url)

    async def discover(
        self,
        seed: NormalizedSeed,
        limits: CrawlLimits,
    ) -> AsyncIterator[DiscoveryBatch]:
        page = await self._require_client().get(
            seed.canonical_url,
            accepted_content_type="xml",
        )
        feed = parse_feed(page.body, source_url=page.url)
        seen: set[str] = set()
        items = []
        for item in feed.items:
            if not self._belongs_to_seed(item, seed):
                continue
            if item.canonical_url in seen:
                continue
            seen.add(item.canonical_url)
            items.append(item)
            if len(items) >= limits.max_articles:
                break
        if not items:
            raise CrawlerDiscoveryError("rss_no_articles")
        yield DiscoveryBatch(
            items=tuple(items),
            frontier_locator=seed.canonical_url,
            continuation=None,
            complete=True,
        )

    async def fetch(self, discovered_item: DiscoveredItem) -> RawPage:
        if discovered_item.embedded_content:
            title = escape(discovered_item.title or "RSS article")
            canonical_url = escape(discovered_item.canonical_url, quote=True)
            body = (
                "<html><head>"
                f'<link rel="canonical" href="{canonical_url}">'
                f'<meta property="og:title" content="{title}">'
                "</head><body><article>"
                f"{discovered_item.embedded_content}"
                "</article></body></html>"
            ).encode("utf-8")
            return RawPage(
                url=discovered_item.canonical_url,
                status_code=200,
                content_type="text/html",
                body=body,
                attempts=1,
            )
        return await self._require_client().get(
            discovered_item.canonical_url,
            accepted_content_type="html",
        )

    def parse(self, raw_page: RawPage) -> NormalizedDocument:
        try:
            html = raw_page.body.decode("utf-8")
        except UnicodeDecodeError:
            raise CrawlerParseError("rss_invalid_response") from None
        return parse_article_html(html, source_url=raw_page.url)

    @staticmethod
    def _belongs_to_seed(item: DiscoveredItem, seed: NormalizedSeed) -> bool:
        parsed = urlsplit(item.canonical_url)
        origin = urlsplit(seed.origin)
        return (
            parsed.scheme == "https"
            and parsed.hostname == origin.hostname
            and parsed.port == origin.port
        )

    def _require_client(self) -> RssHttpClient:
        if self._entered_client is None:
            raise RuntimeError("RssAdapter must be used as an async context manager")
        return self._entered_client  # type: ignore[return-value]


register_adapter(RssAdapter())
