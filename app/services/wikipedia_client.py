import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import math
import random
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.services.wikipedia_types import (
    FetchedWikipediaArticle,
    WikipediaCategoryBatch,
    WikipediaCategoryReference,
    WikipediaPageReference,
    wikipedia_article_url,
)

logger = logging.getLogger(__name__)

_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({408, 429})


class WikipediaRequestError(Exception):
    def __init__(self, code: str, *, attempts: int) -> None:
        super().__init__(code)
        self.code = code
        self.attempts = attempts


class WikipediaTransientError(WikipediaRequestError):
    pass


class WikipediaPermanentError(WikipediaRequestError):
    pass


class AsyncRequestRateLimiter:
    def __init__(
        self,
        requests_per_second: float,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._next_allowed_start: float | None = None

    async def wait(self) -> None:
        async with self._lock:
            now = self._monotonic()
            if self._next_allowed_start is None:
                reserved_start = now
            else:
                reserved_start = max(now, self._next_allowed_start)
            self._next_allowed_start = reserved_start + self._interval
            delay = reserved_start - now
            if delay > 0:
                await self._sleep(delay)


@dataclass(frozen=True)
class _ResponsePayload:
    body: bytes
    attempts: int


class _RetryableResponse(Exception):
    def __init__(self, status: int, retry_after: float | None) -> None:
        super().__init__(status)
        self.status = status
        self.retry_after = retry_after


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _remove_cookie_header(request: httpx.Request) -> None:
    request.headers.pop("Cookie", None)


class WikipediaClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] = utc_now,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.settings = settings
        self._sleep = sleep
        self._monotonic = monotonic
        self._utcnow = utcnow
        self._jitter = jitter
        self._rate_limiter = AsyncRequestRateLimiter(
            settings.wikipedia_requests_per_second,
            sleep=sleep,
            monotonic=monotonic,
        )
        self._semaphore = asyncio.Semaphore(settings.wikipedia_concurrency)
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            headers={"User-Agent": settings.wikipedia_user_agent},
            event_hooks={"request": [_remove_cookie_header]},
            timeout=httpx.Timeout(
                settings.wikipedia_request_timeout_seconds
            ),
            transport=transport,
        )

    async def __aenter__(self) -> "WikipediaClient":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def discover_category(
        self,
        category: str,
        continuation: dict[str, Any] | None,
    ) -> WikipediaCategoryBatch:
        params: dict[str, Any] = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmnamespace": "0|14",
            "cmtype": "page|subcat",
            "cmsort": "sortkey",
            "cmdir": "asc",
            "cmlimit": "50",
            "format": "json",
            "formatversion": "2",
        }
        if continuation is not None:
            params.update(continuation)

        response = await self._request(
            operation="discover_category",
            url=self.settings.wikipedia_action_api_url,
            params=params,
            accepted_content_type="json",
        )
        return self._parse_category_batch(response)

    async def fetch_article(self, title: str) -> FetchedWikipediaArticle:
        encoded_title = quote(title.replace(" ", "_"), safe="")
        url = (
            f"{self.settings.wikipedia_rest_api_url.rstrip('/')}"
            f"/page/{encoded_title}/html"
        )
        response = await self._request(
            operation="fetch_article",
            url=url,
            params=None,
            accepted_content_type="html",
        )
        try:
            html = response.body.decode("utf-8")
        except UnicodeDecodeError:
            raise WikipediaPermanentError(
                "wikipedia_invalid_response",
                attempts=response.attempts,
            ) from None
        return FetchedWikipediaArticle(
            title=title,
            canonical_url=wikipedia_article_url(title),
            html=html,
            attempts=response.attempts,
        )

    async def _request(
        self,
        *,
        operation: str,
        url: str,
        params: dict[str, Any] | None,
        accepted_content_type: str,
    ) -> _ResponsePayload:
        endpoint_host = httpx.URL(url).host
        maximum_attempts = self.settings.wikipedia_fetch_attempts

        for attempt in range(1, maximum_attempts + 1):
            started_at = self._monotonic()
            self._log_event(
                "wikipedia_request_attempt",
                operation=operation,
                endpoint_host=endpoint_host,
                status=None,
                attempt=attempt,
                delay=None,
                duration_ms=0.0,
                outcome="started",
            )
            try:
                body, status = await self._perform_attempt(
                    url=url,
                    params=params,
                    accepted_content_type=accepted_content_type,
                    attempt=attempt,
                )
            except WikipediaPermanentError as error:
                duration_ms = self._duration_ms(started_at)
                self._log_event(
                    "wikipedia_request_complete",
                    operation=operation,
                    endpoint_host=endpoint_host,
                    status=getattr(error, "_http_status", None),
                    attempt=attempt,
                    delay=None,
                    duration_ms=duration_ms,
                    outcome="permanent_error",
                )
                raise
            except _RetryableResponse as error:
                duration_ms = self._duration_ms(started_at)
                if attempt == maximum_attempts:
                    self._log_event(
                        "wikipedia_request_complete",
                        operation=operation,
                        endpoint_host=endpoint_host,
                        status=error.status,
                        attempt=attempt,
                        delay=None,
                        duration_ms=duration_ms,
                        outcome="exhausted",
                    )
                    raise WikipediaTransientError(
                        "wikipedia_request_failed",
                        attempts=attempt,
                    ) from None
                delay = self._retry_delay(attempt, error.retry_after)
                self._log_retry(
                    operation=operation,
                    endpoint_host=endpoint_host,
                    status=error.status,
                    attempt=attempt,
                    delay=delay,
                    duration_ms=duration_ms,
                )
                await self._sleep(delay)
            except httpx.RequestError:
                duration_ms = self._duration_ms(started_at)
                if attempt == maximum_attempts:
                    self._log_event(
                        "wikipedia_request_complete",
                        operation=operation,
                        endpoint_host=endpoint_host,
                        status=None,
                        attempt=attempt,
                        delay=None,
                        duration_ms=duration_ms,
                        outcome="exhausted",
                    )
                    raise WikipediaTransientError(
                        "wikipedia_request_failed",
                        attempts=attempt,
                    ) from None
                delay = self._retry_delay(attempt, None)
                self._log_retry(
                    operation=operation,
                    endpoint_host=endpoint_host,
                    status=None,
                    attempt=attempt,
                    delay=delay,
                    duration_ms=duration_ms,
                )
                await self._sleep(delay)
            else:
                self._log_event(
                    "wikipedia_request_complete",
                    operation=operation,
                    endpoint_host=endpoint_host,
                    status=status,
                    attempt=attempt,
                    delay=None,
                    duration_ms=self._duration_ms(started_at),
                    outcome="success",
                )
                return _ResponsePayload(body=body, attempts=attempt)

        raise AssertionError("request attempt loop did not terminate")

    async def _perform_attempt(
        self,
        *,
        url: str,
        params: dict[str, Any] | None,
        accepted_content_type: str,
        attempt: int,
    ) -> tuple[bytes, int]:
        configured_origin = self._origin(httpx.URL(url))
        current_url = httpx.URL(url)
        current_params = params
        redirects = 0

        while True:
            await self._rate_limiter.wait()
            async with self._semaphore:
                async with self._client.stream(
                    "GET",
                    current_url,
                    params=current_params,
                    headers={
                        "Accept": (
                            "application/json"
                            if accepted_content_type == "json"
                            else "text/html"
                        )
                    },
                ) as response:
                    status = response.status_code
                    if status in _REDIRECT_STATUSES:
                        location = response.headers.get("Location")
                        if location is None or redirects >= _MAX_REDIRECTS:
                            raise self._permanent_error(
                                "wikipedia_redirect_rejected",
                                attempt=attempt,
                                status=status,
                            )
                        try:
                            redirect_url = response.url.join(location)
                        except (httpx.InvalidURL, ValueError):
                            raise self._permanent_error(
                                "wikipedia_redirect_rejected",
                                attempt=attempt,
                                status=status,
                            ) from None
                        if self._origin(redirect_url) != configured_origin:
                            raise self._permanent_error(
                                "wikipedia_redirect_rejected",
                                attempt=attempt,
                                status=status,
                            )
                        redirects += 1
                        current_url = redirect_url
                        current_params = None
                        continue

                    if status in _RETRYABLE_STATUSES or 500 <= status <= 599:
                        raise _RetryableResponse(
                            status,
                            self._parse_retry_after(
                                response.headers.get("Retry-After")
                            ),
                        )
                    if status == 404:
                        raise self._permanent_error(
                            "wikipedia_not_found",
                            attempt=attempt,
                            status=status,
                        )
                    if 400 <= status <= 499:
                        raise self._permanent_error(
                            "wikipedia_request_rejected",
                            attempt=attempt,
                            status=status,
                        )
                    if not 200 <= status <= 299:
                        raise self._permanent_error(
                            "wikipedia_request_rejected",
                            attempt=attempt,
                            status=status,
                        )
                    if not self._content_type_is_accepted(
                        response.headers.get("Content-Type"),
                        accepted_content_type,
                    ):
                        raise self._permanent_error(
                            "wikipedia_invalid_content_type",
                            attempt=attempt,
                            status=status,
                        )
                    body = await self._read_limited_body(
                        response,
                        attempt=attempt,
                    )
                    return body, status

    async def _read_limited_body(
        self,
        response: httpx.Response,
        *,
        attempt: int,
    ) -> bytes:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if (
                len(body) + len(chunk)
                > self.settings.wikipedia_max_response_bytes
            ):
                raise self._permanent_error(
                    "wikipedia_response_too_large",
                    attempt=attempt,
                    status=response.status_code,
                )
            body.extend(chunk)
        return bytes(body)

    def _parse_category_batch(
        self,
        response: _ResponsePayload,
    ) -> WikipediaCategoryBatch:
        try:
            payload = json.loads(response.body)
            if not isinstance(payload, dict):
                raise ValueError
            query = payload.get("query")
            if not isinstance(query, dict):
                raise ValueError
            members = query.get("categorymembers")
            if not isinstance(members, list):
                raise ValueError

            pages = []
            subcategories = []
            for member in members:
                if not isinstance(member, dict):
                    raise ValueError
                namespace = member.get("ns")
                if type(namespace) is not int:
                    raise ValueError
                if namespace not in (0, 14):
                    continue
                page_id = member.get("pageid")
                title = member.get("title")
                if type(page_id) is not int or not isinstance(title, str):
                    raise ValueError
                if namespace == 0:
                    pages.append(WikipediaPageReference(page_id, title))
                else:
                    subcategories.append(
                        WikipediaCategoryReference(page_id, title)
                    )

            continuation = payload.get("continue")
            if continuation is not None and not isinstance(
                continuation,
                dict,
            ):
                raise ValueError
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
            raise WikipediaPermanentError(
                "wikipedia_invalid_response",
                attempts=response.attempts,
            ) from None

        return WikipediaCategoryBatch(
            pages=tuple(pages),
            subcategories=tuple(subcategories),
            continuation=continuation,
        )

    def _parse_retry_after(self, value: str | None) -> float | None:
        if value is None:
            return None
        try:
            numeric_delay = float(value)
        except ValueError:
            numeric_delay = None
        if (
            numeric_delay is not None
            and math.isfinite(numeric_delay)
            and numeric_delay >= 0
        ):
            return numeric_delay

        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        now = self._utcnow()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - now).total_seconds())

    def _retry_delay(
        self,
        attempt: int,
        retry_after: float | None,
    ) -> float:
        if retry_after is not None:
            return retry_after
        return self._jitter(0.0, float(2**attempt))

    def _duration_ms(self, started_at: float) -> float:
        return float(max(0.0, self._monotonic() - started_at) * 1000.0)

    def _log_retry(
        self,
        *,
        operation: str,
        endpoint_host: str,
        status: int | None,
        attempt: int,
        delay: float,
        duration_ms: float,
    ) -> None:
        self._log_event(
            "wikipedia_request_complete",
            operation=operation,
            endpoint_host=endpoint_host,
            status=status,
            attempt=attempt,
            delay=delay,
            duration_ms=duration_ms,
            outcome="retryable_error",
        )
        self._log_event(
            "wikipedia_request_retry",
            operation=operation,
            endpoint_host=endpoint_host,
            status=status,
            attempt=attempt,
            delay=delay,
            duration_ms=duration_ms,
            outcome="retrying",
        )

    @staticmethod
    def _log_event(
        event: str,
        *,
        operation: str,
        endpoint_host: str,
        status: int | None,
        attempt: int,
        delay: float | None,
        duration_ms: float,
        outcome: str,
    ) -> None:
        logger.info(
            event,
            extra={
                "operation": operation,
                "endpoint_host": endpoint_host,
                "status": status,
                "attempt": attempt,
                "delay": delay,
                "duration_ms": duration_ms,
                "outcome": outcome,
            },
        )

    @staticmethod
    def _content_type_is_accepted(
        value: str | None,
        expected: str,
    ) -> bool:
        if value is None:
            return False
        media_type = value.partition(";")[0].strip().casefold()
        if expected == "html":
            return media_type == "text/html"
        return media_type == "application/json" or (
            media_type.startswith("application/")
            and media_type.endswith("+json")
        )

    @staticmethod
    def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
        return url.scheme.casefold(), url.host.casefold(), url.port

    @staticmethod
    def _permanent_error(
        code: str,
        *,
        attempt: int,
        status: int | None,
    ) -> WikipediaPermanentError:
        error = WikipediaPermanentError(code, attempts=attempt)
        error._http_status = status
        return error


def create_wikipedia_client(
    settings: Settings | None = None,
) -> WikipediaClient:
    return WikipediaClient(settings or get_settings())
