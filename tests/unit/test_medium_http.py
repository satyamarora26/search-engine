import asyncio
from dataclasses import replace

import httpx
import pytest

from app.core.config import get_settings
from app.services.crawl_types import (
    CrawlerPolicyError,
    CrawlerPermanentError,
    CrawlerTransientError,
)
from app.services.medium_http import MediumHttpClient


def medium_settings(**overrides):
    values = {
        "medium_user_agent": "CrawlerTest/1.0 (test@example.com)",
        "medium_concurrency": 2,
        "medium_requests_per_second": 1000.0,
        "medium_request_timeout_seconds": 2.0,
        "medium_max_response_bytes": 4096,
        "medium_fetch_attempts": 3,
    }
    values.update(overrides)
    return replace(get_settings(), **values)


def test_client_fetches_robots_once_and_sends_identifying_user_agent():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nAllow: /\n",
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b"<article>article body</article>",
            request=request,
        )

    async def scenario():
        async with MediumHttpClient(
            medium_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            first = await client.get(
                "https://medium.test/article-one",
                accepted_content_type="html",
            )
            second = await client.get(
                "https://medium.test/article-two",
                accepted_content_type="html",
            )
            return first, second

    first, second = asyncio.run(scenario())

    assert [request.url.path for request in requests] == [
        "/robots.txt",
        "/article-one",
        "/article-two",
    ]
    assert all(
        request.headers["user-agent"] == "CrawlerTest/1.0 (test@example.com)"
        for request in requests
    )
    assert first.attempts == 1
    assert second.attempts == 1


def test_client_blocks_disallowed_urls_before_requesting_content():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow: /private\n",
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<article>secret</article>",
            request=request,
        )

    async def scenario():
        async with MediumHttpClient(
            medium_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(CrawlerPolicyError) as caught:
                await client.get(
                    "https://medium.test/private/article",
                    accepted_content_type="html",
                )
            return caught.value

    error = asyncio.run(scenario())

    assert error.code == "medium_robots_denied"
    assert [request.url.path for request in requests] == ["/robots.txt"]


def test_client_retries_server_errors_with_bounded_attempts():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", request=request)
        status = 500 if len(requests) == 2 else 200
        return httpx.Response(
            status,
            headers={"Content-Type": "text/html"},
            content=b"<article>retry body</article>",
            request=request,
        )

    async def scenario():
        async with MediumHttpClient(
            medium_settings(medium_fetch_attempts=2),
            transport=httpx.MockTransport(handler),
            sleep=lambda _delay: asyncio.sleep(0),
            jitter=lambda _low, _high: 0.0,
        ) as client:
            return await client.get(
                "https://medium.test/retry",
                accepted_content_type="html",
            )

    page = asyncio.run(scenario())

    assert page.attempts == 2
    assert [request.url.path for request in requests] == [
        "/robots.txt",
        "/retry",
        "/retry",
    ]


@pytest.mark.parametrize(
    ("response", "error_type", "code"),
    [
        (
            httpx.Response(200, headers={"Content-Type": "application/json"}, content=b"{}"),
            CrawlerPermanentError,
            "medium_invalid_content_type",
        ),
        (
            httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"x" * 101),
            CrawlerPermanentError,
            "medium_response_too_large",
        ),
        (
            httpx.Response(404, headers={"Content-Type": "text/html"}, content=b"missing"),
            CrawlerPermanentError,
            "medium_not_found",
        ),
    ],
)
def test_client_maps_permanent_response_policies(response, error_type, code):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", request=request)
        response.request = request
        return response

    async def scenario():
        async with MediumHttpClient(
            medium_settings(medium_max_response_bytes=100),
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(error_type) as caught:
                await client.get(
                    "https://medium.test/article",
                    accepted_content_type="html",
                )
            return caught.value

    error = asyncio.run(scenario())

    assert error.code == code


def test_client_exhausts_connection_retries_as_transient_error():
    attempts = 0

    def handler(request):
        nonlocal attempts
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", request=request)
        attempts += 1
        raise httpx.ConnectError("connection down", request=request)

    async def scenario():
        async with MediumHttpClient(
            medium_settings(medium_fetch_attempts=2),
            transport=httpx.MockTransport(handler),
            sleep=lambda _delay: asyncio.sleep(0),
            jitter=lambda _low, _high: 0.0,
        ) as client:
            with pytest.raises(CrawlerTransientError) as caught:
                await client.get(
                    "https://medium.test/article",
                    accepted_content_type="html",
                )
            return caught.value

    error = asyncio.run(scenario())

    assert attempts == 2
    assert error.code == "medium_request_failed"
