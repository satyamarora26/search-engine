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
    CrawlerPermanentError,
    CrawlerPolicyError,
    DiscoveredItem,
    DiscoveryBatch,
    NormalizedDocument,
    NormalizedSeed,
    RawPage,
)
from app.services.medium_http import MediumHttpClient, create_medium_http_client
from app.services.medium_parsing import (
    normalize_medium_url,
    parse_article_html,
    parse_rss_feed,
    parse_rss_publication_path,
    parse_sitemap,
)


def normalize_medium_publication_url(seed_url: str) -> NormalizedSeed:
    try:
        parsed = httpx.URL(seed_url.strip())
    except httpx.InvalidURL:
        raise CrawlerPolicyError("medium_invalid_seed") from None
    host = (parsed.host or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username not in (None, "")
        or parsed.password not in (None, "")
        or parsed.query
        or parsed.fragment
        or not (host == "medium.com" or host.endswith(".medium.com"))
    ):
        raise CrawlerPolicyError("medium_invalid_seed")

    path = parsed.path.rstrip("/")
    segments = [segment for segment in path.split("/") if segment]
    if host == "medium.com":
        if len(segments) != 1 or segments[0].startswith("@"):
            raise CrawlerPolicyError("medium_invalid_seed")
        if segments[0] == "p":
            raise CrawlerPolicyError("medium_invalid_seed")
        publication_path = f"/{segments[0]}"
    else:
        if len(segments) > 1 or (segments and segments[0].startswith("@")):
            raise CrawlerPolicyError("medium_invalid_seed")
        publication_path = f"/{segments[0]}" if segments else "/"

    canonical = urlunsplit(("https", host, publication_path, "", ""))
    return NormalizedSeed(
        source_key="medium",
        canonical_url=canonical,
        origin=f"https://{host}",
        publication_path=publication_path,
    )


def medium_feed_url(seed: NormalizedSeed) -> str:
    if seed.origin == "https://medium.com":
        return f"{seed.origin}/feed{seed.publication_path}"
    return f"{seed.origin}/feed"


def medium_sitemap_url(seed: NormalizedSeed) -> str:
    return f"{seed.origin}/sitemap.xml"


class MediumAdapter:
    source_key = "medium"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client_factory: Callable[[], MediumHttpClient] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client_factory = client_factory or (
            lambda: create_medium_http_client(self.settings)
        )
        self._client: MediumHttpClient | None = None
        self._entered_client: object | None = None

    async def __aenter__(self) -> "MediumAdapter":
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
        return normalize_medium_publication_url(seed_url)

    async def discover(
        self,
        seed: NormalizedSeed,
        limits: CrawlLimits,
    ) -> AsyncIterator[DiscoveryBatch]:
        client = self._require_client()
        seen: set[str] = set()
        discovered_count = 0
        rss_url = medium_feed_url(seed)
        publication_path = seed.publication_path
        try:
            rss_page = await client.get(rss_url, accepted_content_type="xml")
            rss_items = parse_rss_feed(rss_page.body)
            rss_publication_path = parse_rss_publication_path(rss_page.body)
            if seed.origin == "https://medium.com" and rss_publication_path:
                publication_path = rss_publication_path
        except (CrawlerPermanentError, CrawlerParseError):
            rss_items = ()

        rss_items = tuple(
            item
            for item in rss_items
            if self._belongs_to_publication(item, seed, publication_path=publication_path)
            and not self._already_seen(item, seen)
        )
        if rss_items:
            limited = rss_items[: limits.max_articles]
            discovered_count += len(limited)
            yield DiscoveryBatch(
                items=limited,
                frontier_locator=rss_url,
                continuation=None,
                complete=discovered_count >= limits.max_articles,
            )
            if discovered_count >= limits.max_articles:
                return

        sitemap_url = medium_sitemap_url(seed)
        sitemap_urls: tuple[str, ...] = ()
        nested_sitemaps: tuple[str, ...] = ()
        try:
            sitemap_page = await client.get(
                sitemap_url,
                accepted_content_type="xml",
            )
            sitemap_urls, nested_sitemaps = parse_sitemap(sitemap_page.body)
        except (CrawlerPermanentError, CrawlerParseError):
            sitemap_urls = ()

        for nested_url in nested_sitemaps:
            if discovered_count >= limits.max_articles:
                break
            try:
                nested_page = await client.get(
                    nested_url,
                    accepted_content_type="xml",
                )
                nested_urls, _ = parse_sitemap(nested_page.body)
            except (CrawlerPermanentError, CrawlerParseError):
                continue
            sitemap_urls += nested_urls

        sitemap_items = []
        for raw_url in sitemap_urls:
            if discovered_count + len(sitemap_items) >= limits.max_articles:
                break
            try:
                canonical = normalize_medium_url(raw_url)
            except CrawlerParseError:
                continue
            item = DiscoveredItem(
                source_item_id=canonical,
                title=None,
                discovered_url=raw_url,
                canonical_url=canonical,
            )
            if not self._belongs_to_publication(
                item,
                seed,
                publication_path=publication_path,
            ):
                continue
            if self._already_seen(item, seen):
                continue
            sitemap_items.append(item)

        if sitemap_items:
            limited_sitemap_items = tuple(
                sitemap_items[: limits.max_articles - discovered_count]
            )
            discovered_count += len(limited_sitemap_items)
            yield DiscoveryBatch(
                items=limited_sitemap_items,
                frontier_locator=sitemap_url,
                continuation=None,
                complete=True,
            )
        elif discovered_count:
            yield DiscoveryBatch(
                items=(),
                frontier_locator=sitemap_url,
                continuation=None,
                complete=True,
            )

        if discovered_count == 0:
            raise CrawlerDiscoveryError("medium_no_articles")

    async def fetch(self, discovered_item: DiscoveredItem) -> RawPage:
        if discovered_item.embedded_content:
            title = escape(discovered_item.title or "Medium article")
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
            raise CrawlerPermanentError("medium_invalid_response") from None
        return parse_article_html(html, source_url=raw_page.url)

    @staticmethod
    def _already_seen(item: DiscoveredItem, seen: set[str]) -> bool:
        if item.canonical_url in seen:
            return True
        seen.add(item.canonical_url)
        return False

    @staticmethod
    def _belongs_to_publication(
        item: DiscoveredItem,
        seed: NormalizedSeed,
        *,
        publication_path: str | None = None,
    ) -> bool:
        parsed = urlsplit(item.canonical_url)
        seed_host = (urlsplit(seed.origin).hostname or "").casefold()
        item_host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or item_host != seed_host:
            return False
        if seed.origin == "https://medium.com":
            scope = publication_path or seed.publication_path
            return parsed.path.startswith(scope + "/")
        return parsed.path not in {"/feed", "/sitemap.xml", "/robots.txt"}

    def _require_client(self) -> MediumHttpClient:
        if self._entered_client is None:
            raise RuntimeError(
                "MediumAdapter must be used as an async context manager"
            )
        return self._entered_client  # type: ignore[return-value]


register_adapter(MediumAdapter())
