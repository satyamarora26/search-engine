from collections.abc import Callable
from typing import Any

from celery import Task
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.documents import DocumentRepository
from app.schemas.search_snapshots import (
    SearchIndexSnapshot,
    SearchSnapshotDocument,
)
from app.services.search_index import SearchIndexService
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)
from app.workers.celery_app import celery_app


def rebuild_search_index_snapshot(
    index_version: str,
    session_factory: Callable[[], Session] = SessionLocal,
    store_factory: Callable[
        [], RedisSearchIndexStore
    ] = create_redis_search_index_store,
) -> dict[str, Any]:
    session = session_factory()
    try:
        documents = DocumentRepository(session).list_all_active()
        status = SearchIndexService(
            documents,
            index_version=index_version,
        ).status()
        snapshot = SearchIndexSnapshot(
            index_version=index_version,
            documents=[
                SearchSnapshotDocument.model_validate(document)
                for document in documents
            ],
        )
        store_factory().publish(snapshot)
        return status.model_dump()
    finally:
        session.close()


@celery_app.task(bind=True, name="search.rebuild_index_snapshot")
def rebuild_search_index_snapshot_task(task: Task) -> dict[str, Any]:
    if task.request.id is None:
        raise RuntimeError("Celery rebuild task id is required.")
    return rebuild_search_index_snapshot(f"redis-{task.request.id}")
