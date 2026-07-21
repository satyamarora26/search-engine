from collections.abc import Callable
import logging
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.job import (
    SEARCH_INDEX_REBUILD_JOB,
    SEARCH_INDEX_RESOURCE,
    Job,
)
from app.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)
REBUILD_PROGRESS_TOTAL = 4


class JobEnqueueError(Exception):
    pass


class JobNotFoundError(Exception):
    pass


class JobStorageError(Exception):
    pass


class IndexJobConflictError(Exception):
    def __init__(self, active_job: Job) -> None:
        super().__init__("A search index job is already active.")
        self.active_job = active_job


class TaskSender(Protocol):
    def apply_async(
        self,
        *,
        args: list[str],
        task_id: str,
    ) -> Any: ...


class JobService:
    def __init__(
        self,
        session: Session,
        rebuild_task: TaskSender,
        *,
        job_id_factory: Callable[[], UUID] = uuid4,
        repository: JobRepository | None = None,
    ) -> None:
        self.session = session
        self.rebuild_task = rebuild_task
        self.job_id_factory = job_id_factory
        self.repository = repository or JobRepository(session)

    def enqueue_search_index_rebuild(self) -> Job:
        active_job = self._get_active_index_job()
        if active_job is not None:
            return self._resolve_rebuild_request(active_job)

        job_id = self.job_id_factory()
        try:
            job = self.repository.create_pending(
                job_id,
                job_type=SEARCH_INDEX_REBUILD_JOB,
                resource_key=SEARCH_INDEX_RESOURCE,
                progress_total=REBUILD_PROGRESS_TOTAL,
                progress_message="Waiting for worker",
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            winning_job = self._get_active_index_job()
            if winning_job is None:
                raise JobStorageError("Job storage unavailable.")
            return self._resolve_rebuild_request(winning_job)
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

        try:
            self.rebuild_task.apply_async(
                args=[str(job_id)],
                task_id=str(job_id),
            )
        except Exception as error:
            self._record_enqueue_failure(job_id)
            raise JobEnqueueError("Could not enqueue background job.") from error
        return job

    def get_job(self, job_id: UUID) -> Job:
        try:
            job = self.repository.get(job_id)
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error
        if job is None:
            raise JobNotFoundError(f"Job {job_id} was not found.")
        return job

    def _get_active_index_job(self) -> Job | None:
        try:
            return self.repository.get_active_by_resource(SEARCH_INDEX_RESOURCE)
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

    @staticmethod
    def _resolve_rebuild_request(active_job: Job) -> Job:
        if active_job.job_type == SEARCH_INDEX_REBUILD_JOB:
            return active_job
        raise IndexJobConflictError(active_job)

    def _record_enqueue_failure(self, job_id: UUID) -> None:
        try:
            self.repository.mark_pending_failure(
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
