import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import delete, select

from app.api.dependencies import get_wikipedia_crawl_service
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import create_app
from app.models.document import Document
from app.models.ingestion_item import (
    IMPORTED_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    IngestionItem,
)
from app.models.job import SUCCESS_STATUS, Job
from app.models.wikipedia_crawl import FAILED_FETCH_STATUS, FETCHED_FETCH_STATUS
from app.services.search_index import SearchIndexService
from app.services.search_index_sync import SearchIndexSynchronizer
from app.services.search_snapshots import (
    ACTIVE_INDEX_VERSION_KEY,
    INDEX_SNAPSHOT_KEY_PREFIX,
    RedisSearchIndexStore,
)
from app.services.wikipedia_crawls import WikipediaCrawlService
from app.services.wikipedia_types import wikipedia_article_url
from app.workers.wikipedia_tasks import wikipedia_crawl_task
from tests.support.fake_wikimedia import FakeWikimediaServer

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 to run live services tests",
    ),
]


class RecordingTaskSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, list[str] | str]] = []

    def apply_async(self, *, args: list[str], task_id: str):
        self.calls.append({"args": args, "task_id": task_id})
        return object()


RESTORE_SNAPSHOT_SCRIPT = """
local active = redis.call('GET', KEYS[1])
if active == ARGV[1] then
    if ARGV[2] == '1' then
        redis.call('SET', KEYS[1], ARGV[3])
    else
        redis.call('DEL', KEYS[1])
    end
end
redis.call('DEL', KEYS[2])
return active
"""


def restore_previous_snapshot(
    redis_client: Redis,
    *,
    created_version: str,
    previous_version: str | None,
) -> None:
    redis_client.eval(
        RESTORE_SNAPSHOT_SCRIPT,
        2,
        ACTIVE_INDEX_VERSION_KEY,
        f"{INDEX_SNAPSHOT_KEY_PREFIX}{created_version}",
        created_version,
        "1" if previous_version is not None else "0",
        previous_version or "",
    )


def test_wikipedia_crawl_runs_from_api_to_bm25_search(monkeypatch):
    marker = f"uniquewikipediacrawlterm{uuid4().hex}"
    existing_url = wikipedia_article_url("Existing search article")
    redis_client = Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
    )
    previous_active_version = redis_client.get(ACTIVE_INDEX_VERSION_KEY)
    job_id: UUID | None = None
    document_ids: list[int] = []
    existing_document_id: int | None = None
    sender = RecordingTaskSender()

    monkeypatch.setenv(
        "WIKIPEDIA_ACTION_API_URL",
        "http://127.0.0.1:0/w/api.php",
    )
    monkeypatch.setenv(
        "WIKIPEDIA_REST_API_URL",
        "http://127.0.0.1:0/w/rest.php/v1",
    )
    monkeypatch.setenv("WIKIPEDIA_REQUESTS_PER_SECOND", "1000")
    monkeypatch.setenv("WIKIPEDIA_REQUEST_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("WIKIPEDIA_FETCH_ATTEMPTS", "3")

    try:
        with FakeWikimediaServer(search_token=marker) as fake:
            monkeypatch.setenv("WIKIPEDIA_ACTION_API_URL", fake.action_api_url)
            monkeypatch.setenv("WIKIPEDIA_REST_API_URL", fake.rest_api_url)
            session = SessionLocal()
            try:
                existing = Document(
                    title="Existing database article",
                    content="This document already exists in PostgreSQL.",
                    url=existing_url,
                )
                session.add(existing)
                session.commit()
                existing_document_id = existing.id
            finally:
                session.close()

            app = create_app()

            def override_crawl_service():
                service_session = SessionLocal()
                try:
                    yield WikipediaCrawlService(service_session, sender)
                finally:
                    service_session.close()

            app.dependency_overrides[get_wikipedia_crawl_service] = (
                override_crawl_service
            )

            try:
                with TestClient(app) as client:
                    accepted = client.post(
                        "/api/v1/crawls/wikipedia",
                        json={
                            "category": "Featured articles",
                            "max_articles": 4,
                            "max_depth": 0,
                        },
                    )
                    assert accepted.status_code == 202
                    job_id = UUID(accepted.json()["job_id"])
                    assert sender.calls == [
                        {"args": [str(job_id)], "task_id": str(job_id)}
                    ]

                    result = wikipedia_crawl_task.apply(
                        args=[str(job_id)],
                        task_id=str(job_id),
                        throw=True,
                    ).get()
                    redelivery_result = wikipedia_crawl_task.apply(
                        args=[str(job_id)],
                        task_id=str(job_id),
                        throw=True,
                    ).get()
                    assert redelivery_result == result

                    status_response = client.get(f"/api/v1/jobs/{job_id}")
                    assert status_response.status_code == 200
                    assert status_response.json()["status"] == SUCCESS_STATUS

                    item_response = client.get(
                        f"/api/v1/crawls/wikipedia/{job_id}/items"
                    )
                    assert item_response.status_code == 200
                    items = item_response.json()["items"]
            finally:
                app.dependency_overrides.clear()

            expected_result = {
                "root_category": "Category:Featured articles",
                "max_articles": 4,
                "max_depth": 0,
                "categories_visited": 1,
                "category_limit_reached": False,
                "discovered_count": 4,
                "fetched_count": 3,
                "imported_count": 2,
                "duplicate_skipped_count": 1,
                "fetch_failed_count": 1,
                "ingestion_failed_count": 0,
                "failed_count": 1,
                "index_rebuilt": True,
                "index_version": f"redis-{job_id}",
            }
            assert result == expected_result
            assert [item["position"] for item in items] == [0, 1, 2, 3]
            assert [item["fetch_status"] for item in items] == [
                FETCHED_FETCH_STATUS,
                FETCHED_FETCH_STATUS,
                FETCHED_FETCH_STATUS,
                FAILED_FETCH_STATUS,
            ]
            assert [item["ingestion_status"] for item in items] == [
                IMPORTED_ITEM_STATUS,
                SKIPPED_ITEM_STATUS,
                IMPORTED_ITEM_STATUS,
                None,
            ]
            assert items[1]["error"] == "duplicate_url"
            assert items[3]["error"] == "wikipedia_not_found"

            assert fake.attempts_for("Retry search article") == 2
            assert fake.redirect_count == 1
            assert sum(
                record["path"].startswith(
                    "/w/rest.php/v1/page/Unique_search_article"
                )
                for record in fake.request_log
            ) == 2
            assert all(
                record["host"] == fake.authority for record in fake.request_log
            )
            assert all(record["user_agent"] for record in fake.request_log)
            assert all(
                record["path"] == "/w/api.php"
                or record["path"].startswith("/w/rest.php/v1/")
                for record in fake.request_log
            )

            snapshot_store = RedisSearchIndexStore(redis_client)
            assert snapshot_store.get_active_version() == f"redis-{job_id}"
            assert (
                redis_client.exists(
                    f"{INDEX_SNAPSHOT_KEY_PREFIX}redis-{job_id}"
                )
                == 1
            )
            search_index = SearchIndexSynchronizer(
                SearchIndexService(),
                snapshot_store,
            ).synchronize()
            search_response = search_index.search(marker)
            assert search_response.index_version == f"redis-{job_id}"
            assert search_response.total_results == 1
            assert search_response.results[0].title == "Unique search article"
    finally:
        if job_id is not None:
            restore_previous_snapshot(
                redis_client,
                created_version=f"redis-{job_id}",
                previous_version=previous_active_version,
            )
        if job_id is not None or existing_document_id is not None:
            cleanup_session = SessionLocal()
            try:
                if job_id is not None:
                    document_ids = list(
                        cleanup_session.scalars(
                            select(IngestionItem.document_id).where(
                                IngestionItem.job_id == job_id,
                                IngestionItem.document_id.is_not(None),
                            )
                        ).all()
                    )
                if existing_document_id is not None:
                    document_ids.append(existing_document_id)
                if job_id is not None:
                    cleanup_session.execute(
                        delete(Job).where(Job.id == job_id)
                    )
                if document_ids:
                    cleanup_session.execute(
                        delete(Document).where(Document.id.in_(document_ids))
                    )
                cleanup_session.commit()
            finally:
                cleanup_session.close()
        redis_client.close()
