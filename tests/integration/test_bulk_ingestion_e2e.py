import os
from uuid import UUID, uuid4

import pytest
from redis import Redis
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.ingestion_item import (
    FAILED_ITEM_STATUS,
    IMPORTED_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    IngestionItem,
)
from app.models.job import SUCCESS_STATUS, Job
from app.repositories.ingestion_items import IngestionItemRepository
from app.repositories.jobs import JobRepository
from app.services.bulk_ingestion import BulkIngestionService
from app.services.search_index import SearchIndexService
from app.services.search_index_sync import SearchIndexSynchronizer
from app.services.search_snapshots import (
    ACTIVE_INDEX_VERSION_KEY,
    INDEX_SNAPSHOT_KEY_PREFIX,
    RedisSearchIndexStore,
)
from app.workers.ingestion_tasks import bulk_ingest_documents_task

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 to run live services tests",
    ),
]


class FakeTaskSender:
    def __init__(self) -> None:
        self.calls = []

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
    active_key: str = ACTIVE_INDEX_VERSION_KEY,
    snapshot_prefix: str = INDEX_SNAPSHOT_KEY_PREFIX,
) -> None:
    redis_client.eval(
        RESTORE_SNAPSHOT_SCRIPT,
        2,
        active_key,
        f"{snapshot_prefix}{created_version}",
        created_version,
        "1" if previous_version is not None else "0",
        previous_version or "",
    )


def test_bulk_ingestion_persists_outcomes_and_publishes_search_snapshot():
    unique_suffix = uuid4().hex
    unique_token = f"uniquebulkingestiontoken{unique_suffix}"
    unique_url = f"https://example.com/bulk/{unique_suffix}"
    payloads = [
        {
            "title": "Bulk BM25 Snapshot",
            "content": unique_token,
            "url": unique_url,
        },
        {
            "title": "Duplicate Bulk BM25 Snapshot",
            "content": "duplicate content",
            "url": unique_url,
        },
        {"title": "Missing content"},
    ]
    redis_client = Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
    )
    previous_active_version = redis_client.get(ACTIVE_INDEX_VERSION_KEY)
    job_id: UUID | None = None
    document_ids: list[int] = []

    try:
        sender = FakeTaskSender()
        session = SessionLocal()
        try:
            job = BulkIngestionService(session, sender).enqueue_documents(
                payloads
            )
            job_id = job.id
        finally:
            session.close()

        assert sender.calls == [
            {"args": [str(job_id)], "task_id": str(job_id)}
        ]

        eager_result = bulk_ingest_documents_task.apply(
            args=[str(job_id)],
            task_id=str(job_id),
            throw=True,
        )
        task_result = eager_result.get()
        expected_result = {
            "received_count": 3,
            "imported_count": 1,
            "skipped_count": 1,
            "failed_count": 1,
            "index_rebuilt": True,
            "index_version": f"redis-{job_id}",
        }
        assert task_result == expected_result

        redelivery_result = bulk_ingest_documents_task.apply(
            args=[str(job_id)],
            task_id=str(job_id),
            throw=True,
        ).get()
        assert redelivery_result == expected_result

        inspection_session = SessionLocal()
        try:
            completed = JobRepository(inspection_session).get(job_id)
            assert completed is not None
            report_items = IngestionItemRepository(
                inspection_session
            ).list_for_job(job_id, limit=100, offset=0)
            document_ids = [
                item.document_id
                for item in report_items
                if item.document_id is not None
            ]

            assert completed.status == SUCCESS_STATUS
            assert completed.result == expected_result
            assert [item.position for item in report_items] == [0, 1, 2]
            assert [item.status for item in report_items] == [
                IMPORTED_ITEM_STATUS,
                SKIPPED_ITEM_STATUS,
                FAILED_ITEM_STATUS,
            ]
            assert report_items[1].error == "duplicate_url"
            assert report_items[2].error == "content: Field required"
        finally:
            inspection_session.close()

        snapshot_store = RedisSearchIndexStore(redis_client)
        assert snapshot_store.get_active_version() == f"redis-{job_id}"
        search_index = SearchIndexSynchronizer(
            SearchIndexService(),
            snapshot_store,
        ).synchronize()
        search_response = search_index.search(unique_token)

        assert search_response.index_version == f"redis-{job_id}"
        assert search_response.total_results == 1
        assert search_response.results[0].title == "Bulk BM25 Snapshot"
        assert search_response.results[0].document_id == document_ids[0]
    finally:
        if job_id is not None:
            restore_previous_snapshot(
                redis_client,
                created_version=f"redis-{job_id}",
                previous_version=previous_active_version,
            )
        redis_client.close()

        if job_id is not None:
            cleanup_session = SessionLocal()
            try:
                if not document_ids:
                    document_ids = list(
                        cleanup_session.scalars(
                            select(IngestionItem.document_id).where(
                                IngestionItem.job_id == job_id,
                                IngestionItem.document_id.is_not(None),
                            )
                        ).all()
                    )
                cleanup_session.execute(
                    delete(IngestionItem).where(
                        IngestionItem.job_id == job_id
                    )
                )
                if document_ids:
                    cleanup_session.execute(
                        delete(Document).where(
                            Document.id.in_(document_ids)
                        )
                    )
                cleanup_session.execute(
                    delete(Job).where(Job.id == job_id)
                )
                cleanup_session.commit()
            finally:
                cleanup_session.close()


def test_snapshot_cleanup_restores_only_pointer_still_owned_by_test():
    suffix = uuid4().hex
    active_key = f"test:bulk-ingestion:{suffix}:active"
    snapshot_prefix = f"test:bulk-ingestion:{suffix}:snapshot:"
    created_version = f"created-{suffix}"
    previous_version = f"previous-{suffix}"
    newer_version = f"newer-{suffix}"
    snapshot_key = f"{snapshot_prefix}{created_version}"
    redis_client = Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
    )

    try:
        redis_client.set(active_key, newer_version)
        redis_client.set(snapshot_key, "temporary snapshot")

        restore_previous_snapshot(
            redis_client,
            created_version=created_version,
            previous_version=previous_version,
            active_key=active_key,
            snapshot_prefix=snapshot_prefix,
        )

        assert redis_client.get(active_key) == newer_version
        assert redis_client.get(snapshot_key) is None

        redis_client.set(active_key, created_version)
        redis_client.set(snapshot_key, "temporary snapshot")

        restore_previous_snapshot(
            redis_client,
            created_version=created_version,
            previous_version=previous_version,
            active_key=active_key,
            snapshot_prefix=snapshot_prefix,
        )

        assert redis_client.get(active_key) == previous_version
        assert redis_client.get(snapshot_key) is None
    finally:
        redis_client.delete(active_key, snapshot_key)
        redis_client.close()
