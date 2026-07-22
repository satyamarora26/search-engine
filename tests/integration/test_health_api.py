from dataclasses import dataclass

from fastapi.testclient import TestClient

import app.api.v1.health as health_module
from app.main import create_app
from app.schemas.search import SearchIndexStatus


@dataclass
class FakeDatabaseSession:
    should_fail: bool = False

    def __enter__(self) -> "FakeDatabaseSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        if self.should_fail:
            raise RuntimeError("database is down")


class FakeRedisClient:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    def ping(self) -> bool:
        if self.should_fail:
            raise RuntimeError("redis is down")
        return True


@dataclass
class FakeRedisStore:
    client: FakeRedisClient


class FakeSearchIndex:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    def status(self) -> SearchIndexStatus:
        if self.should_fail:
            raise RuntimeError("index is down")
        return SearchIndexStatus(
            index_version="redis-v4",
            document_count=12,
        )


def test_health_reports_all_dependencies_when_available(monkeypatch):
    monkeypatch.setattr(
        health_module,
        "SessionLocal",
        lambda: FakeDatabaseSession(),
    )
    monkeypatch.setattr(
        health_module,
        "create_redis_search_index_store",
        lambda: FakeRedisStore(FakeRedisClient()),
    )
    monkeypatch.setattr(
        health_module,
        "get_search_index_service",
        lambda: FakeSearchIndex(),
    )

    response = TestClient(create_app()).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "checks": {
            "api": {"status": "healthy", "detail": None},
            "database": {"status": "healthy", "detail": None},
            "redis": {"status": "healthy", "detail": None},
            "search_index": {
                "status": "healthy",
                "detail": "Index redis-v4 contains 12 documents.",
            },
        },
    }


def test_health_reports_degraded_dependencies_without_exposing_errors(
    monkeypatch,
):
    monkeypatch.setattr(
        health_module,
        "SessionLocal",
        lambda: FakeDatabaseSession(should_fail=True),
    )
    monkeypatch.setattr(
        health_module,
        "create_redis_search_index_store",
        lambda: FakeRedisStore(FakeRedisClient(should_fail=True)),
    )
    monkeypatch.setattr(
        health_module,
        "get_search_index_service",
        lambda: FakeSearchIndex(should_fail=True),
    )

    response = TestClient(create_app()).get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["api"] == {
        "status": "healthy",
        "detail": None,
    }
    assert payload["checks"]["database"] == {
        "status": "unhealthy",
        "detail": "Database unavailable.",
    }
    assert payload["checks"]["redis"] == {
        "status": "unhealthy",
        "detail": "Redis unavailable.",
    }
    assert payload["checks"]["search_index"] == {
        "status": "unhealthy",
        "detail": "Search index unavailable.",
    }
