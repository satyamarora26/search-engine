import asyncio
from collections.abc import Awaitable, Callable
import random
import time
from urllib import robotparser

import httpx

from app.core.config import Settings, get_settings
from app.services.crawl_types import (
    CrawlerPermanentError,
    CrawlerPolicyError,
    CrawlerTransientError,
    RawPage,
)
from app.services.wikipedia_client import AsyncRequestRateLimiter


class MediumHttpClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.settings = settings
        self._sleep = sleep
        self._jitter = jitter
        self._robots: dict[tuple[str, str, int | None], robotparser.RobotFileParser] = {}
        self._rate_limiter = AsyncRequestRateLimiter(
            settings.medium_requests_per_second,
            sleep=sleep,
            monotonic=monotonic,
        )
        self._semaphore = asyncio.Semaphore(settings.medium_concurrency)
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            headers={"User-Agent": settings.medium_user_agent},
            timeout=httpx.Timeout(settings.medium_request_timeout_seconds),
            transport=transport,
        )

    async def __aenter__(self) -> "MediumHttpClient":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, *, accepted_content_type: str) -> RawPage:
        target = httpx.URL(url)
        await self._ensure_robots(target)
        parser = self._robots[self._origin(target)]
        if not parser.can_fetch(self.settings.medium_user_agent, str(target)):
            raise CrawlerPolicyError("medium_robots_denied")

        for attempt in range(1, self.settings.medium_fetch_attempts + 1):
            try:
                return await self._perform_attempt(
                    target,
                    accepted_content_type=accepted_content_type,
                    attempt=attempt,
                )
            except CrawlerTransientError as error:
                if attempt == self.settings.medium_fetch_attempts:
                    raise CrawlerTransientError(
                        error.code,
                        attempts=attempt,
                    ) from None
                await self._sleep(self._retry_delay(attempt))
            except httpx.RequestError:
                if attempt == self.settings.medium_fetch_attempts:
                    raise CrawlerTransientError(
                        "medium_request_failed",
                        attempts=attempt,
                    ) from None
                await self._sleep(self._retry_delay(attempt))

        raise AssertionError("request attempt loop did not terminate")

    async def _ensure_robots(self, target: httpx.URL) -> None:
        origin = self._origin(target)
        if origin in self._robots:
            return

        robots_url = f"{target.scheme}://{target.host}"
        if target.port is not None:
            robots_url += f":{target.port}"
        robots_url += "/robots.txt"

        for attempt in range(1, self.settings.medium_discovery_attempts + 1):
            try:
                await self._rate_limiter.wait()
                async with self._semaphore:
                    response = await self._client.get(robots_url)
                if response.status_code == 404:
                    parser = robotparser.RobotFileParser()
                    parser.set_url(robots_url)
                    parser.parse([])
                    self._robots[origin] = parser
                    return
                if 500 <= response.status_code <= 599:
                    raise CrawlerTransientError(
                        "medium_robots_unavailable",
                        attempts=attempt,
                    )
                if not 200 <= response.status_code <= 299:
                    raise CrawlerPolicyError("medium_robots_unavailable")
                body = response.content
                if len(body) > self.settings.medium_max_response_bytes:
                    raise CrawlerPolicyError("medium_robots_too_large")
                parser = robotparser.RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
                self._robots[origin] = parser
                return
            except CrawlerTransientError:
                if attempt == self.settings.medium_discovery_attempts:
                    raise
                await self._sleep(self._retry_delay(attempt))
            except httpx.RequestError:
                if attempt == self.settings.medium_discovery_attempts:
                    raise CrawlerTransientError(
                        "medium_robots_unavailable",
                        attempts=attempt,
                    ) from None
                await self._sleep(self._retry_delay(attempt))

        raise AssertionError("robots attempt loop did not terminate")

    async def _perform_attempt(
        self,
        target: httpx.URL,
        *,
        accepted_content_type: str,
        attempt: int,
    ) -> RawPage:
        await self._rate_limiter.wait()
        async with self._semaphore:
            async with self._client.stream("GET", target) as response:
                status = response.status_code
                if status == 429 or 500 <= status <= 599:
                    raise CrawlerTransientError(
                        "medium_request_failed",
                        attempts=attempt,
                    )
                if status == 404:
                    raise CrawlerPermanentError(
                        "medium_not_found",
                        attempts=attempt,
                    )
                if 400 <= status <= 499 or not 200 <= status <= 299:
                    raise CrawlerPermanentError(
                        "medium_request_rejected",
                        attempts=attempt,
                    )
                content_type = response.headers.get("Content-Type", "")
                if not self._content_type_is_accepted(
                    content_type,
                    accepted_content_type,
                ):
                    raise CrawlerPermanentError(
                        "medium_invalid_content_type",
                        attempts=attempt,
                    )
                body = await self._read_limited_body(response)

        return RawPage(
            url=str(response.url),
            status_code=status,
            content_type=content_type,
            body=body,
            attempts=attempt,
        )

    async def _read_limited_body(self, response: httpx.Response) -> bytes:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > self.settings.medium_max_response_bytes:
                raise CrawlerPermanentError("medium_response_too_large")
            body.extend(chunk)
        if not body:
            raise CrawlerPermanentError("medium_empty_response")
        return bytes(body)

    def _retry_delay(self, attempt: int) -> float:
        return self._jitter(0.0, float(min(2**attempt, 8)))

    @staticmethod
    def _content_type_is_accepted(value: str, expected: str) -> bool:
        media_type = value.partition(";")[0].strip().casefold()
        if expected == "html":
            return media_type == "text/html" or media_type == "application/xhtml+xml"
        if expected == "xml":
            return media_type in {
                "application/xml",
                "text/xml",
                "application/rss+xml",
                "application/atom+xml",
            }
        return media_type == expected.casefold()

    @staticmethod
    def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
        return url.scheme.casefold(), (url.host or "").casefold(), url.port


def create_medium_http_client(settings: Settings | None = None) -> MediumHttpClient:
    return MediumHttpClient(settings or get_settings())
