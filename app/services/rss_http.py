from collections.abc import Awaitable, Callable

import httpx

from app.core.config import Settings, get_settings
from app.services.medium_http import MediumHttpClient


class RssHttpClient(MediumHttpClient):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] | None = None,
        jitter: Callable[[float, float], float] | None = None,
    ) -> None:
        worker_settings = settings or get_settings()
        kwargs = {
            "transport": transport,
            "error_prefix": "rss",
            "user_agent": worker_settings.rss_user_agent,
            "concurrency": worker_settings.rss_concurrency,
            "requests_per_second": worker_settings.rss_requests_per_second,
            "request_timeout_seconds": worker_settings.rss_request_timeout_seconds,
            "max_response_bytes": worker_settings.rss_max_response_bytes,
            "fetch_attempts": worker_settings.rss_fetch_attempts,
            "discovery_attempts": worker_settings.rss_discovery_attempts,
        }
        if sleep is not None:
            kwargs["sleep"] = sleep
        if monotonic is not None:
            kwargs["monotonic"] = monotonic
        if jitter is not None:
            kwargs["jitter"] = jitter
        super().__init__(worker_settings, **kwargs)


def create_rss_http_client(settings: Settings | None = None) -> RssHttpClient:
    return RssHttpClient(settings or get_settings())
