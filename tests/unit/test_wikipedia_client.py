import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import logging
from urllib.parse import quote

import httpx
import pytest

from app.core.config import get_settings
from app.services.wikipedia_client import (
    AsyncRequestRateLimiter,
    WikipediaClient,
    WikipediaPermanentError,
    WikipediaTransientError,
    create_wikipedia_client,
)
from app.services.wikipedia_types import (
    FetchedWikipediaArticle,
    WikipediaCategoryReference,
    WikipediaPageReference,
    wikipedia_article_url,
)


ACTION_RESPONSE = {
    "continue": {"cmcontinue": "page|next", "continue": "-||"},
    "query": {
        "categorymembers": [
            {"pageid": 10, "ns": 0, "title": "BM25"},
            {
                "pageid": 20,
                "ns": 14,
                "title": "Category:Search algorithms",
            },
        ]
    },
}


def wikipedia_settings(**overrides):
    values = {
        "wikipedia_action_api_url": (
            "https://en.wikipedia.org/w/api.php"
        ),
        "wikipedia_rest_api_url": (
            "https://en.wikipedia.org/w/rest.php/v1"
        ),
        "wikipedia_user_agent": "CrawlerTest/1.0 (test@example.com)",
        "wikipedia_requests_per_second": 1000.0,
    }
    values.update(overrides)
    return replace(get_settings(), **values)


def client_for_handler(handler, **client_kwargs):
    return WikipediaClient(
        wikipedia_settings(),
        transport=httpx.MockTransport(handler),
        **client_kwargs,
    )


def test_discovery_sends_structured_parameters_and_parses_namespaces():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=ACTION_RESPONSE, request=request)

    async def scenario():
        async with client_for_handler(handler) as client:
            return await client.discover_category(
                "Category:Information retrieval",
                {"cmcontinue": "page|start", "continue": "-||"},
            )

    batch = asyncio.run(scenario())

    assert batch.pages == (WikipediaPageReference(page_id=10, title="BM25"),)
    assert batch.subcategories == (
        WikipediaCategoryReference(
            page_id=20,
            title="Category:Search algorithms",
        ),
    )
    assert batch.continuation == ACTION_RESPONSE["continue"]

    assert len(requests) == 1
    assert dict(requests[0].url.params) == {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": "Category:Information retrieval",
        "cmnamespace": "0|14",
        "cmtype": "page|subcat",
        "cmsort": "sortkey",
        "cmdir": "asc",
        "cmlimit": "50",
        "format": "json",
        "formatversion": "2",
        "cmcontinue": "page|start",
        "continue": "-||",
    }


def test_discovery_ignores_other_namespaces_and_allows_no_continuation():
    response = {
        "query": {
            "categorymembers": [
                {"pageid": 30, "ns": 1, "title": "Talk:BM25"},
                {"pageid": 10, "ns": 0, "title": "BM25"},
            ]
        }
    }

    async def scenario():
        async with client_for_handler(
            lambda request: httpx.Response(
                200,
                json=response,
                request=request,
            )
        ) as client:
            return await client.discover_category("Category:Search", None)

    batch = asyncio.run(scenario())

    assert batch.pages == (WikipediaPageReference(10, "BM25"),)
    assert batch.subcategories == ()
    assert batch.continuation is None


def test_article_title_and_canonical_url_are_encoded_as_paths():
    requests = []
    title = "Why? / खोज space"

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b"<html><p>search result</p></html>",
            request=request,
        )

    async def scenario():
        async with client_for_handler(handler) as client:
            return await client.fetch_article(title)

    article = asyncio.run(scenario())
    encoded_title = quote(title.replace(" ", "_"), safe="")

    assert requests[0].url.raw_path == (
        f"/w/rest.php/v1/page/{encoded_title}/html".encode()
    )
    assert article == FetchedWikipediaArticle(
        title=title,
        canonical_url=wikipedia_article_url(title),
        html="<html><p>search result</p></html>",
        attempts=1,
    )


def test_rate_limiter_spaces_reserved_starts():
    now = [10.0]
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    limiter = AsyncRequestRateLimiter(
        2.0,
        sleep=sleep,
        monotonic=lambda: now[0],
    )

    async def scenario():
        starts = []
        for _ in range(3):
            await limiter.wait()
            starts.append(now[0])
        return starts

    starts = asyncio.run(scenario())

    assert starts == [10.0, 10.5, 11.0]
    assert sleeps == [0.5, 0.5]


def test_client_spaces_request_starts_with_one_shared_limiter():
    now = [0.0]
    starts = []

    async def sleep(delay):
        now[0] += delay

    def handler(request):
        starts.append(now[0])
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<p>article</p>",
            request=request,
        )

    settings = wikipedia_settings(wikipedia_requests_per_second=2.0)

    async def scenario():
        async with WikipediaClient(
            settings,
            transport=httpx.MockTransport(handler),
            sleep=sleep,
            monotonic=lambda: now[0],
        ) as client:
            await client.fetch_article("One")
            await client.fetch_article("Two")
            await client.fetch_article("Three")

    asyncio.run(scenario())

    assert starts == [0.0, 0.5, 1.0]


def test_only_configured_number_of_requests_can_be_in_flight():
    started = 0
    active = 0
    maximum_active = 0

    async def scenario():
        nonlocal started, active, maximum_active
        four_started = asyncio.Event()
        release = asyncio.Event()

        async def handler(request):
            nonlocal started, active, maximum_active
            started += 1
            active += 1
            maximum_active = max(maximum_active, active)
            if started == 4:
                four_started.set()
            await release.wait()
            active -= 1
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=b"<p>article</p>",
                request=request,
            )

        settings = wikipedia_settings(
            wikipedia_concurrency=4,
            wikipedia_requests_per_second=100_000.0,
        )
        async with WikipediaClient(
            settings,
            transport=httpx.MockTransport(handler),
        ) as client:
            tasks = [
                asyncio.create_task(client.fetch_article(f"Page {index}"))
                for index in range(5)
            ]
            await asyncio.wait_for(four_started.wait(), timeout=1.0)
            await asyncio.sleep(0.01)
            assert started == 4
            release.set()
            await asyncio.gather(*tasks)

    asyncio.run(scenario())

    assert started == 5
    assert maximum_active == 4


def test_numeric_retry_after_is_honored_before_success():
    calls = 0
    now = [0.0]
    sleeps = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "3"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<p>article</p>",
            request=request,
        )

    async def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    async def scenario():
        async with client_for_handler(
            handler,
            sleep=sleep,
            monotonic=lambda: now[0],
            jitter=lambda _low, _high: pytest.fail("jitter was used"),
        ) as client:
            return await client.fetch_article("Retry")

    article = asyncio.run(scenario())

    assert article.attempts == 2
    assert calls == 2
    assert sleeps == [3.0]


def test_http_date_retry_after_uses_injected_utc_clock():
    calls = 0
    now = [0.0]
    current_utc = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)
    retry_at = format_datetime(current_utc + timedelta(seconds=7), usegmt=True)
    sleeps = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503,
                headers={"Retry-After": retry_at},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<p>article</p>",
            request=request,
        )

    async def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    async def scenario():
        async with client_for_handler(
            handler,
            sleep=sleep,
            monotonic=lambda: now[0],
            utcnow=lambda: current_utc,
            jitter=lambda _low, _high: pytest.fail("jitter was used"),
        ) as client:
            return await client.fetch_article("Retry date")

    article = asyncio.run(scenario())

    assert article.attempts == 2
    assert sleeps == [7.0]


@pytest.mark.parametrize("failure", ["timeout", 408, 429, 500])
def test_transient_failures_exhaust_after_exact_attempt_limit(failure):
    calls = 0
    tick = 0.0

    def monotonic():
        nonlocal tick
        tick += 1.0
        return tick

    def handler(request):
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("request timed out", request=request)
        return httpx.Response(failure, request=request)

    async def no_sleep(_delay):
        return None

    async def scenario():
        async with client_for_handler(
            handler,
            sleep=no_sleep,
            monotonic=monotonic,
            jitter=lambda _low, _high: 0.0,
        ) as client:
            with pytest.raises(WikipediaTransientError) as caught:
                await client.fetch_article("Unavailable")
            return caught.value

    error = asyncio.run(scenario())

    assert error.code == "wikipedia_request_failed"
    assert error.attempts == 3
    assert str(error) == "wikipedia_request_failed"
    assert calls == 3


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (404, "wikipedia_not_found"),
        (400, "wikipedia_request_rejected"),
        (403, "wikipedia_request_rejected"),
    ],
)
def test_permanent_http_errors_are_not_retried(status, expected_code):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            content=b"DISTINCTIVE PRIVATE ERROR BODY",
            request=request,
        )

    async def scenario():
        async with client_for_handler(handler) as client:
            with pytest.raises(WikipediaPermanentError) as caught:
                await client.fetch_article("Rejected")
            return caught.value

    error = asyncio.run(scenario())

    assert error.code == expected_code
    assert error.attempts == 1
    assert "DISTINCTIVE" not in str(error)
    assert calls == 1


def test_oversized_stream_is_rejected_without_retry():
    calls = 0
    settings = wikipedia_settings(wikipedia_max_response_bytes=5)

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"123456",
            request=request,
        )

    async def scenario():
        async with WikipediaClient(
            settings,
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(WikipediaPermanentError) as caught:
                await client.fetch_article("Large")
            return caught.value

    error = asyncio.run(scenario())

    assert error.code == "wikipedia_response_too_large"
    assert error.attempts == 1
    assert calls == 1


def test_wrong_content_types_are_stable_permanent_errors():
    async def scenario():
        def html_for_json(request):
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=b"DISTINCTIVE JSON ENDPOINT BODY",
                request=request,
            )

        async with client_for_handler(html_for_json) as client:
            with pytest.raises(WikipediaPermanentError) as json_error:
                await client.discover_category("Category:Search", None)

        def json_for_html(request):
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b'"DISTINCTIVE HTML ENDPOINT BODY"',
                request=request,
            )

        async with client_for_handler(json_for_html) as client:
            with pytest.raises(WikipediaPermanentError) as html_error:
                await client.fetch_article("Wrong type")

        return json_error.value, html_error.value

    json_error, html_error = asyncio.run(scenario())

    for error in (json_error, html_error):
        assert error.code == "wikipedia_invalid_content_type"
        assert error.attempts == 1
        assert "DISTINCTIVE" not in str(error)


@pytest.mark.parametrize(
    "body",
    [
        b"{not-json DISTINCTIVE",
        json.dumps({"query": {"categorymembers": {}}}).encode(),
        json.dumps(
            {
                "query": {
                    "categorymembers": [
                        {"pageid": "10", "ns": 0, "title": "BM25"}
                    ]
                }
            }
        ).encode(),
        json.dumps(
            {
                "continue": "not-an-object",
                "query": {"categorymembers": []},
            }
        ).encode(),
    ],
)
def test_malformed_action_responses_are_stable_permanent_errors(body):
    def handler(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=body,
            request=request,
        )

    async def scenario():
        async with client_for_handler(handler) as client:
            with pytest.raises(WikipediaPermanentError) as caught:
                await client.discover_category("Category:Search", None)
            return caught.value

    error = asyncio.run(scenario())

    assert error.code == "wikipedia_invalid_response"
    assert error.attempts == 1
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert "DISTINCTIVE" not in str(error)


def test_invalid_utf8_html_is_a_stable_permanent_error():
    def handler(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"\xff\xfe",
            request=request,
        )

    async def scenario():
        async with client_for_handler(handler) as client:
            with pytest.raises(WikipediaPermanentError) as caught:
                await client.fetch_article("Invalid encoding")
            return caught.value

    error = asyncio.run(scenario())

    assert error.code == "wikipedia_invalid_response"
    assert error.attempts == 1
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


def test_cross_host_redirect_is_rejected_before_external_request():
    requested_urls = []

    def handler(request):
        requested_urls.append(str(request.url))
        if request.url.host == "evil.example":
            pytest.fail("external redirect was requested")
        return httpx.Response(
            302,
            headers={"Location": "https://evil.example/private"},
            request=request,
        )

    async def scenario():
        async with client_for_handler(handler) as client:
            with pytest.raises(WikipediaPermanentError) as caught:
                await client.fetch_article("Redirect")
            return caught.value

    error = asyncio.run(scenario())

    assert error.code == "wikipedia_redirect_rejected"
    assert error.attempts == 1
    assert len(requested_urls) == 1


def test_same_host_redirect_is_followed_within_the_same_attempt():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/html"):
            return httpx.Response(
                302,
                headers={"Location": "/rendered/article"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<p>redirected article</p>",
            request=request,
        )

    async def scenario():
        async with client_for_handler(handler) as client:
            return await client.fetch_article("Redirect")

    article = asyncio.run(scenario())

    assert paths == [
        "/w/rest.php/v1/page/Redirect/html",
        "/rendered/article",
    ]
    assert article.attempts == 1


def test_more_than_five_redirects_are_rejected():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            302,
            headers={"Location": f"/redirect/{calls}"},
            request=request,
        )

    async def scenario():
        async with client_for_handler(handler) as client:
            with pytest.raises(WikipediaPermanentError) as caught:
                await client.fetch_article("Redirect loop")
            return caught.value

    error = asyncio.run(scenario())

    assert error.code == "wikipedia_redirect_rejected"
    assert error.attempts == 1
    assert calls == 6


def test_every_request_identifies_the_client_without_sending_cookies():
    headers = []

    def handler(request):
        headers.append(request.headers)
        if request.url.path.endswith("api.php"):
            return httpx.Response(
                200,
                json={"query": {"categorymembers": []}},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<p>article</p>",
            request=request,
        )

    async def scenario():
        async with client_for_handler(handler) as client:
            await client.discover_category("Category:Search", None)
            await client.fetch_article("BM25")

    asyncio.run(scenario())

    assert len(headers) == 2
    for request_headers in headers:
        assert request_headers["User-Agent"] == (
            "CrawlerTest/1.0 (test@example.com)"
        )
        assert "cookie" not in request_headers


def test_server_set_cookies_are_not_replayed_on_redirects():
    headers = []

    def handler(request):
        headers.append(request.headers)
        if len(headers) == 1:
            return httpx.Response(
                302,
                headers={
                    "Location": "/rendered/article",
                    "Set-Cookie": "session=private-token; Path=/",
                },
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<p>article</p>",
            request=request,
        )

    async def scenario():
        async with client_for_handler(handler) as client:
            return await client.fetch_article("Cookie redirect")

    asyncio.run(scenario())

    assert len(headers) == 2
    assert all("cookie" not in request_headers for request_headers in headers)


def test_logs_request_lifecycle_without_response_bodies(caplog):
    calls = 0
    distinctive_json = "PRIVATE-JSON-BODY-731"
    distinctive_html = "PRIVATE-ARTICLE-CONTENT-947"
    tick = 0.0

    def monotonic():
        nonlocal tick
        tick += 1.0
        return tick

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                500,
                headers={"Content-Type": "application/json"},
                content=distinctive_json.encode(),
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=f"<p>{distinctive_html}</p>".encode(),
            request=request,
        )

    async def no_sleep(_delay):
        return None

    caplog.set_level(logging.INFO, logger="app.services.wikipedia_client")

    async def scenario():
        async with client_for_handler(
            handler,
            sleep=no_sleep,
            monotonic=monotonic,
            jitter=lambda _low, _high: 0.0,
        ) as client:
            return await client.fetch_article("Logging")

    article = asyncio.run(scenario())

    assert distinctive_html in article.html
    records = [
        record
        for record in caplog.records
        if record.name == "app.services.wikipedia_client"
    ]
    assert {record.getMessage() for record in records} >= {
        "wikipedia_request_attempt",
        "wikipedia_request_retry",
        "wikipedia_request_complete",
    }
    for record in records:
        assert record.operation == "fetch_article"
        assert record.endpoint_host == "en.wikipedia.org"
        assert hasattr(record, "status")
        assert isinstance(record.attempt, int)
        assert isinstance(record.duration_ms, float)
        assert isinstance(record.outcome, str)

    serialized_logs = "\n".join(
        f"{record.getMessage()} {record.__dict__!r}" for record in records
    )
    assert distinctive_json not in serialized_logs
    assert distinctive_html not in serialized_logs


def test_factory_uses_explicit_settings():
    settings = wikipedia_settings()

    client = create_wikipedia_client(settings)

    assert isinstance(client, WikipediaClient)
    assert client.settings is settings
    asyncio.run(client.aclose())
