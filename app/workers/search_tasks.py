from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.documents import DocumentRepository
from app.services.search_index import SearchIndexService
from app.workers.celery_app import celery_app

WORKER_SEARCH_INDEX_SNAPSHOT_VERSION = "celery-postgres-snapshot-v1"


def rebuild_search_index_snapshot(
    session_factory: Callable[[], Session] = SessionLocal,
) -> dict[str, Any]:
    session = session_factory()
    try:
        documents = DocumentRepository(session).list_all_active()
        status = SearchIndexService(
            documents,
            index_version=WORKER_SEARCH_INDEX_SNAPSHOT_VERSION,
        ).status()
        return status.model_dump()
    finally:
        session.close()


@celery_app.task(name="search.rebuild_index_snapshot")
def rebuild_search_index_snapshot_task() -> dict[str, Any]:
    return rebuild_search_index_snapshot()
