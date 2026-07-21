from collections.abc import Callable
import logging
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.ingestion_item import IngestionItem
from app.models.job import (
    BULK_DOCUMENT_INGESTION_JOB,
    SEARCH_INDEX_RESOURCE,
    Job,
)
from app.repositories.ingestion_items import IngestionItemRepository
from app.repositories.jobs import JobRepository
from app.services.jobs import (
    IndexJobConflictError,
    JobEnqueueError,
    JobStorageError,
    TaskSender,
)

logger = logging.getLogger(__name__)


class BulkIngestionNotFoundError(Exception):
    pass


class BulkIngestionService:
    def __init__(
        self,
        session: Session,
        task: TaskSender,
        *,
        job_id_factory: Callable[[], UUID] = uuid4,
        job_repository: JobRepository | None = None,
        item_repository: IngestionItemRepository | None = None,
    ) -> None:
        self.session = session
        self.task = task
        self.job_id_factory = job_id_factory
        self.jobs = job_repository or JobRepository(session)
        self.items = item_repository or IngestionItemRepository(session)

    def enqueue_documents(self, payloads: list[JsonValue]) -> Job:
        active_job = self._get_active_index_job()
        if active_job is not None:
            raise IndexJobConflictError(active_job)

        job_id = self.job_id_factory()
        try:
            job = self.jobs.create_pending(
                job_id,
                job_type=BULK_DOCUMENT_INGESTION_JOB,
                resource_key=SEARCH_INDEX_RESOURCE,
                progress_total=len(payloads) + 1,
                progress_message="Waiting for worker",
            )
            self.items.stage_many(job_id, payloads)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            winner = self._get_active_index_job()
            if winner is None:
                raise JobStorageError("Job storage unavailable.")
            raise IndexJobConflictError(winner)
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

        try:
            self.task.apply_async(
                args=[str(job_id)],
                task_id=str(job_id),
            )
        except Exception as error:
            self._record_enqueue_failure(job_id)
            raise JobEnqueueError(
                "Could not enqueue background job."
            ) from error
        return job

    def list_items(
        self,
        job_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[int, list[IngestionItem]]:
        try:
            job = self.jobs.get(job_id)
            if (
                job is None
                or job.job_type != BULK_DOCUMENT_INGESTION_JOB
            ):
                raise BulkIngestionNotFoundError(
                    f"Bulk ingestion job {job_id} was not found."
                )
            total = self.items.count_for_job(job_id)
            items = self.items.list_for_job(
                job_id,
                limit=limit,
                offset=offset,
            )
            return total, items
        except BulkIngestionNotFoundError:
            raise
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

    def _get_active_index_job(self) -> Job | None:
        try:
            return self.jobs.get_active_by_resource(SEARCH_INDEX_RESOURCE)
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

    def _record_enqueue_failure(self, job_id: UUID) -> None:
        try:
            self.jobs.mark_pending_failure(
                job_id,
                error="Could not enqueue background job.",
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            logger.exception(
                "Could not persist enqueue failure for job %s.",
                job_id,
            )
