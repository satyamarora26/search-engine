from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.job import (
    BULK_DOCUMENT_INGESTION_JOB,
    FAILURE_STATUS,
    PENDING_STATUS,
    SUCCESS_STATUS,
)
from app.repositories.ingestion_items import (
    IngestionCounts,
    IngestionItemRepository,
)
from app.services.document_ingestion import IngestionItemProcessor
from app.services.job_tracker import JobTracker, JobTransitionError
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)
from app.workers.search_tasks import rebuild_search_index_snapshot

T = TypeVar("T")


class IngestionItemStore:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        repository_factory: Callable[
            [Session], IngestionItemRepository
        ] = IngestionItemRepository,
    ) -> None:
        self.session_factory = session_factory
        self.repository_factory = repository_factory

    def list_pending_ids(self, job_id: UUID) -> list[int]:
        return self._read(
            lambda repository: repository.list_pending_ids(job_id)
        )

    def count_terminal(self, job_id: UUID) -> int:
        return self._read(
            lambda repository: repository.count_terminal(job_id)
        )

    def counts(self, job_id: UUID) -> IngestionCounts:
        return self._read(lambda repository: repository.counts(job_id))

    def _read(self, operation: Callable[[IngestionItemRepository], T]) -> T:
        session = self.session_factory()
        try:
            return operation(self.repository_factory(session))
        finally:
            session.close()


class BulkIngestionRunner:
    def __init__(
        self,
        tracker: JobTracker | None = None,
        item_store: IngestionItemStore | None = None,
        processor: IngestionItemProcessor | None = None,
        rebuild: Callable[
            [str], dict[str, Any]
        ] = rebuild_search_index_snapshot,
        snapshot_store: RedisSearchIndexStore | None = None,
    ) -> None:
        self.tracker = tracker or JobTracker()
        self.item_store = item_store or IngestionItemStore()
        self.processor = processor or IngestionItemProcessor()
        self.rebuild = rebuild
        self.snapshot_store = (
            snapshot_store or create_redis_search_index_store()
        )

    def run(self, job_id: UUID) -> dict[str, Any]:
        job = self.tracker.get_job(job_id)
        if job is None or job.job_type != BULK_DOCUMENT_INGESTION_JOB:
            raise JobTransitionError(
                "Bulk ingestion job is missing or invalid."
            )
        if job.status == SUCCESS_STATUS:
            return dict(job.result or {})
        if job.status == FAILURE_STATUS:
            raise JobTransitionError(
                "Bulk ingestion job has already failed."
            )
        if job.progress_total is None or job.progress_total < 2:
            raise JobTransitionError(
                "Bulk ingestion job has invalid progress metadata."
            )
        if job.status == PENDING_STATUS:
            claimed = self.tracker.claim(
                job_id,
                progress_current=0,
                progress_total=job.progress_total,
                progress_message="Processing documents",
            )
            if not claimed:
                raise JobTransitionError(
                    "Bulk ingestion job could not be claimed."
                )

        pending_ids = self.item_store.list_pending_ids(job_id)
        completed = self.item_store.count_terminal(job_id)
        for item_id in pending_ids:
            self.processor.process(item_id)
            completed += 1
            self.tracker.update_progress(
                job_id,
                progress_current=completed,
                progress_total=job.progress_total,
                progress_message=(
                    f"Processed document {completed} "
                    f"of {job.progress_total - 1}"
                ),
            )

        counts = self.item_store.counts(job_id)
        result = self._publish_or_reuse_index(job_id, counts)
        self.tracker.mark_success(
            job_id,
            result=result,
            progress_total=counts.received + 1,
            progress_message="Bulk ingestion completed",
        )
        return result

    def _publish_or_reuse_index(
        self,
        job_id: UUID,
        counts: IngestionCounts,
    ) -> dict[str, Any]:
        if counts.imported:
            self.tracker.update_progress(
                job_id,
                progress_current=counts.received,
                progress_total=counts.received + 1,
                progress_message="Rebuilding search index",
            )
            status = self.rebuild(f"redis-{job_id}")
            index_version = status["index_version"]
            index_rebuilt = True
        else:
            self.tracker.update_progress(
                job_id,
                progress_current=counts.received,
                progress_total=counts.received + 1,
                progress_message="No index changes required",
            )
            index_version = self.snapshot_store.get_active_version()
            index_rebuilt = False

        return {
            "received_count": counts.received,
            "imported_count": counts.imported,
            "skipped_count": counts.skipped,
            "failed_count": counts.failed,
            "index_rebuilt": index_rebuilt,
            "index_version": index_version,
        }
