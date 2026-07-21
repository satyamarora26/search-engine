import pytest

from app.core.config import (
    DEFAULT_DATABASE_URL,
    DEFAULT_WIKIPEDIA_ACTION_API_URL,
    DEFAULT_WIKIPEDIA_REST_API_URL,
    DEFAULT_WIKIPEDIA_USER_AGENT,
    get_settings,
)


def test_default_database_url_uses_postgresql_psycopg(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = get_settings()

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_database_url_can_be_overridden(monkeypatch):
    database_url = "postgresql+psycopg://user:pass@localhost:5432/test_db"
    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = get_settings()

    assert settings.database_url == database_url


def test_default_wikipedia_settings_are_bounded_and_identifying(monkeypatch):
    for name in (
        "WIKIPEDIA_ACTION_API_URL",
        "WIKIPEDIA_REST_API_URL",
        "WIKIPEDIA_USER_AGENT",
        "WIKIPEDIA_CONCURRENCY",
        "WIKIPEDIA_REQUESTS_PER_SECOND",
        "WIKIPEDIA_REQUEST_TIMEOUT_SECONDS",
        "WIKIPEDIA_MAX_RESPONSE_BYTES",
        "WIKIPEDIA_MAX_CATEGORIES",
        "WIKIPEDIA_FETCH_ATTEMPTS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.wikipedia_action_api_url == (
        DEFAULT_WIKIPEDIA_ACTION_API_URL
    )
    assert settings.wikipedia_rest_api_url == DEFAULT_WIKIPEDIA_REST_API_URL
    assert settings.wikipedia_user_agent == DEFAULT_WIKIPEDIA_USER_AGENT
    assert settings.wikipedia_concurrency == 4
    assert settings.wikipedia_requests_per_second == 2.0
    assert settings.wikipedia_request_timeout_seconds == 30.0
    assert settings.wikipedia_max_response_bytes == 10 * 1024 * 1024
    assert settings.wikipedia_max_categories == 100
    assert settings.wikipedia_fetch_attempts == 3


def test_wikipedia_settings_accept_stripped_test_server_overrides(monkeypatch):
    monkeypatch.setenv(
        "WIKIPEDIA_ACTION_API_URL",
        "  http://127.0.0.1:8765/action  ",
    )
    monkeypatch.setenv(
        "WIKIPEDIA_REST_API_URL",
        "  http://127.0.0.1:8765/rest  ",
    )
    monkeypatch.setenv(
        "WIKIPEDIA_USER_AGENT",
        "  CrawlerTest/1.0 (test@example.com)  ",
    )
    monkeypatch.setenv("WIKIPEDIA_CONCURRENCY", "2")
    monkeypatch.setenv("WIKIPEDIA_REQUESTS_PER_SECOND", "50")
    monkeypatch.setenv("WIKIPEDIA_REQUEST_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("WIKIPEDIA_MAX_RESPONSE_BYTES", "4096")
    monkeypatch.setenv("WIKIPEDIA_MAX_CATEGORIES", "7")
    monkeypatch.setenv("WIKIPEDIA_FETCH_ATTEMPTS", "2")

    settings = get_settings()

    assert settings.wikipedia_action_api_url == "http://127.0.0.1:8765/action"
    assert settings.wikipedia_rest_api_url == "http://127.0.0.1:8765/rest"
    assert settings.wikipedia_user_agent == (
        "CrawlerTest/1.0 (test@example.com)"
    )
    assert settings.wikipedia_concurrency == 2
    assert settings.wikipedia_requests_per_second == 50.0
    assert settings.wikipedia_request_timeout_seconds == 2.5
    assert settings.wikipedia_max_response_bytes == 4096
    assert settings.wikipedia_max_categories == 7
    assert settings.wikipedia_fetch_attempts == 2


@pytest.mark.parametrize(
    "user_agent",
    ["", "   ", "python-httpx/0.28", "python-requests/2.32", "curl/8.0"],
)
def test_wikipedia_settings_reject_blank_or_generic_user_agents(
    monkeypatch,
    user_agent,
):
    monkeypatch.setenv("WIKIPEDIA_USER_AGENT", user_agent)

    with pytest.raises(ValueError, match="WIKIPEDIA_USER_AGENT"):
        get_settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WIKIPEDIA_CONCURRENCY", "0"),
        ("WIKIPEDIA_REQUESTS_PER_SECOND", "-1"),
        ("WIKIPEDIA_REQUEST_TIMEOUT_SECONDS", "0"),
        ("WIKIPEDIA_MAX_RESPONSE_BYTES", "-10"),
        ("WIKIPEDIA_MAX_CATEGORIES", "0"),
        ("WIKIPEDIA_FETCH_ATTEMPTS", "-1"),
    ],
)
def test_wikipedia_settings_reject_nonpositive_limits(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        get_settings()
