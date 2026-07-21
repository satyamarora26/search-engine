from collections.abc import Callable
import logging
from typing import Any
from uuid import UUID

from celery import Task
from celery.exceptions import Ignore
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)
from sqlalchemy.exc import OperationalError

from app.models.job import STARTED_STATUS
from app.services.advisory_locks import (
    JobAlreadyRunningError,
    PostgresAdvisoryLock,
)
from app.services.bulk_ingestion_runner import BulkIngestionRunner
from app.services.job_tracker import JobTracker
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
TRANSIENT_ERRORS = (
    OperationalError,
    RedisConnectionError,
    RedisTimeoutError,
)


@celery_app.task(
    bind=True,
    name="documents.bulk_ingest",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def bulk_ingest_documents_task(
    task: Task,
    job_id: str,
) -> dict[str, Any]:
    if task.request.id is None or task.request.id != job_id:
        raise RuntimeError(
            "Celery task id does not match durable job id."
        )
    return execute_bulk_ingestion_attempt(
        task,
        UUID(job_id),
        runner_factory=BulkIngestionRunner,
        lock_factory=PostgresAdvisoryLock,
        tracker_factory=JobTracker,
    )


def execute_bulk_ingestion_attempt(
    task: Task,
    job_id: UUID,
    *,
    runner_factory: Callable[[], BulkIngestionRunner],
    lock_factory: Callable[[], PostgresAdvisoryLock],
    tracker_factory: Callable[[], JobTracker],
) -> dict[str, Any]:
    tracker = tracker_factory()
    try:
        with lock_factory().acquire(job_id):
            return runner_factory().run(job_id)
    except JobAlreadyRunningError as error:
        raise Ignore() from error
    except TRANSIENT_ERRORS as error:
        if task.request.retries < task.max_retries:
            _record_retry_progress(tracker, job_id)
            raise task.retry(
                exc=error,
                countdown=2 ** (task.request.retries + 1),
            )
        logger.exception(
            "Bulk ingestion job %s exhausted retries.",
            job_id,
        )
        _record_final_failure(tracker, job_id)
        raise
    except Exception:
        logger.exception("Bulk ingestion job %s failed.", job_id)
        _record_final_failure(tracker, job_id)
        raise


def _record_retry_progress(tracker: JobTracker, job_id: UUID) -> None:
    try:
        job = tracker.get_job(job_id)
        if job is not None and job.status == STARTED_STATUS:
            tracker.update_progress(
                job_id,
                progress_current=job.progress_current,
                progress_total=job.progress_total,
                progress_message="Temporary failure; retrying",
            )
    except Exception:
        logger.exception(
            "Could not record retry progress for job %s.",
            job_id,
        )


def _record_final_failure(tracker: JobTracker, job_id: UUID) -> None:
    try:
        tracker.mark_failure(job_id, error="Bulk ingestion failed.")
    except Exception:
        logger.exception(
            "Could not record failure for job %s.",
            job_id,
        )
