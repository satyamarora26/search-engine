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

from app.models.job import MEDIUM_CRAWL_JOB, RSS_CRAWL_JOB, STARTED_STATUS
from app.services.advisory_locks import (
    JobAlreadyRunningError,
    PostgresAdvisoryLock,
)
from app.services.crawl_types import CrawlerTransientError
from app.services.crawl_runner import CrawlRunner, medium_crawl_config, rss_crawl_config
from app.services.job_tracker import JobTracker
from app.services import medium_adapter as _medium_adapter
from app.services import rss_adapter as _rss_adapter
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

TRANSIENT_ERRORS = (
    OperationalError,
    RedisConnectionError,
    RedisTimeoutError,
    CrawlerTransientError,
)


@celery_app.task(
    bind=True,
    name="crawl.medium",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def crawl_medium_task(task: Task, job_id: str) -> dict[str, Any]:
    if task.request.id is None or task.request.id != job_id:
        raise RuntimeError("Celery task id does not match durable job id.")
    return execute_crawl_attempt(
        task,
        UUID(job_id),
        runner_factory=lambda: CrawlRunner(config=medium_crawl_config()),
        lock_factory=PostgresAdvisoryLock,
        tracker_factory=JobTracker,
        expected_job_type=MEDIUM_CRAWL_JOB,
        failure_message="Medium crawl failed.",
    )


@celery_app.task(
    bind=True,
    name="crawl.rss",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def crawl_rss_task(task: Task, job_id: str) -> dict[str, Any]:
    if task.request.id is None or task.request.id != job_id:
        raise RuntimeError("Celery task id does not match durable job id.")
    return execute_rss_crawl_attempt(
        task,
        UUID(job_id),
        runner_factory=lambda: CrawlRunner(config=rss_crawl_config()),
        lock_factory=PostgresAdvisoryLock,
        tracker_factory=JobTracker,
    )


def execute_medium_crawl_attempt(
    task: Task,
    job_id: UUID,
    *,
    runner_factory: Callable[[], CrawlRunner],
    lock_factory: Callable[[], PostgresAdvisoryLock],
    tracker_factory: Callable[[], JobTracker],
) -> dict[str, Any]:
    return execute_crawl_attempt(
        task,
        job_id,
        runner_factory=runner_factory,
        lock_factory=lock_factory,
        tracker_factory=tracker_factory,
        expected_job_type=MEDIUM_CRAWL_JOB,
        failure_message="Medium crawl failed.",
    )


def execute_rss_crawl_attempt(
    task: Task,
    job_id: UUID,
    *,
    runner_factory: Callable[[], CrawlRunner],
    lock_factory: Callable[[], PostgresAdvisoryLock],
    tracker_factory: Callable[[], JobTracker],
) -> dict[str, Any]:
    return execute_crawl_attempt(
        task,
        job_id,
        runner_factory=runner_factory,
        lock_factory=lock_factory,
        tracker_factory=tracker_factory,
        expected_job_type=RSS_CRAWL_JOB,
        failure_message="RSS crawl failed.",
    )


def execute_crawl_attempt(
    task: Task,
    job_id: UUID,
    *,
    runner_factory: Callable[[], CrawlRunner],
    lock_factory: Callable[[], PostgresAdvisoryLock],
    tracker_factory: Callable[[], JobTracker],
    expected_job_type: str,
    failure_message: str,
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
        logger.exception("Crawl job %s exhausted retries.", job_id)
        _record_final_failure(tracker, job_id, expected_job_type, failure_message)
        raise
    except Exception:
        logger.exception("Crawl job %s failed.", job_id)
        _record_final_failure(tracker, job_id, expected_job_type, failure_message)
        raise


def _record_retry_progress(tracker: JobTracker, job_id: UUID) -> None:
    try:
        job = tracker.get_job(job_id)
        if job is not None and job.status == STARTED_STATUS:
            tracker.update_progress(
                job_id,
                progress_current=job.progress_current,
                progress_total=job.progress_total,
                progress_message="Temporary crawler failure; retrying",
            )
    except Exception:
        logger.exception("Could not record crawler retry progress for %s.", job_id)


def _record_final_failure(
    tracker: JobTracker,
    job_id: UUID,
    expected_job_type: str,
    failure_message: str,
) -> None:
    try:
        job = tracker.get_job(job_id)
        if job is None or job.job_type != expected_job_type:
            return
        tracker.mark_failure(job_id, error=failure_message)
    except Exception:
        logger.exception("Could not record crawl failure for %s.", job_id)
