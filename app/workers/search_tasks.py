from collections.abc import Callable
import logging
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.documents import DocumentRepository
from app.schemas.search_snapshots import (
    SearchIndexSnapshot,
    SearchSnapshotDocument,
)
from app.services.job_tracker import JobTracker
from app.services.search_index import SearchIndexService
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
REBUILD_PROGRESS_TOTAL = 4


def rebuild_search_index_snapshot(
    index_version: str,
    session_factory: Callable[[], Session] = SessionLocal,
    store_factory: Callable[
        [], RedisSearchIndexStore
    ] = create_redis_search_index_store,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    session = session_factory()
    try:
        documents = DocumentRepository(session).list_all_active()
        if progress_callback is not None:
            progress_callback(2, "Building search index")

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
        if progress_callback is not None:
            progress_callback(3, "Publishing search snapshot")

        store_factory().publish(snapshot)
        return status.model_dump()
    finally:
        session.close()


def execute_rebuild_search_index_job(
    job_id: str,
    celery_task_id: str,
    *,
    tracker_factory: Callable[[], JobTracker] = JobTracker,
    rebuild: Callable[..., dict[str, Any]] = rebuild_search_index_snapshot,
) -> dict[str, Any]:
    if job_id != celery_task_id:
        raise RuntimeError("Celery task id does not match durable job id.")

    durable_job_id = UUID(job_id)
    tracker = tracker_factory()
    claimed = tracker.claim(
        durable_job_id,
        progress_current=1,
        progress_total=REBUILD_PROGRESS_TOTAL,
        progress_message="Loading documents",
    )
    if not claimed:
        raise RuntimeError("Durable job is missing or not pending.")

    try:
        result = rebuild(
            f"redis-{job_id}",
            progress_callback=lambda current, message: tracker.update_progress(
                durable_job_id,
                progress_current=current,
                progress_total=REBUILD_PROGRESS_TOTAL,
                progress_message=message,
            ),
        )
        tracker.mark_success(
            durable_job_id,
            result=result,
            progress_total=REBUILD_PROGRESS_TOTAL,
            progress_message="Search index rebuilt",
        )
        return result
    except Exception:
        logger.exception("Search index rebuild job %s failed.", job_id)
        try:
            tracker.mark_failure(
                durable_job_id,
                error="Search index rebuild failed.",
            )
        except Exception:
            logger.exception("Could not record failure for job %s.", job_id)
        raise


@celery_app.task(bind=True, name="search.rebuild_index_snapshot")
def rebuild_search_index_snapshot_task(
    task: Task,
    job_id: str,
) -> dict[str, Any]:
    if task.request.id is None:
        raise RuntimeError("Celery rebuild task id is required.")
    return execute_rebuild_search_index_job(job_id, str(task.request.id))
