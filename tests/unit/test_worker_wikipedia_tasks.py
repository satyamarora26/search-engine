from contextlib import contextmanager
import logging
from types import SimpleNamespace
from uuid import UUID

import pytest
from celery.exceptions import Ignore
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)
from sqlalchemy.exc import OperationalError

from app.models.job import (
    BULK_DOCUMENT_INGESTION_JOB,
    STARTED_STATUS,
    WIKIPEDIA_CRAWL_JOB,
)
from app.services.advisory_locks import JobAlreadyRunningError
from app.services.job_tracker import JobTransitionError
from app.services.wikipedia_client import WikipediaTransientError
from app.services.wikipedia_crawl_runner import WikipediaCrawlCompletionError
from app.workers.wikipedia_tasks import (
    execute_wikipedia_crawl_attempt,
    wikipedia_crawl_task,
)


JOB_ID = UUID("ed8bff1d-6986-47ad-bad6-dd802e677ccc")
OTHER_JOB_ID = UUID("a227c489-2185-4a61-876b-9f6fb3566d33")
SUCCESS_RESULT = {
    "root_category": "Category:Root",
    "discovered_count": 2,
    "index_version": f"redis-{JOB_ID}",
}


class FakeRetry(Exception):
    pass


class FakeTaskContext:
    def __init__(self, *, retries=0):
        self.request = SimpleNamespace(retries=retries)
        self.max_retries = 3
        self.retry_with = None

    def retry(self, **values):
        self.retry_with = values
        raise FakeRetry()


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.error = None

    def run(self, job_id):
        self.calls.append(job_id)
        if self.error is not None:
            raise self.error
        return SUCCESS_RESULT


class FakeLock:
    def __init__(self):
        self.acquired = True
        self.job_ids = []

    @contextmanager
    def acquire(self, job_id):
        self.job_ids.append(job_id)
        if not self.acquired:
            raise JobAlreadyRunningError(f"Job {job_id} is already running.")
        yield


class FakeTracker:
    def __init__(self):
        self.job = SimpleNamespace(
            id=JOB_ID,
            job_type=WIKIPEDIA_CRAWL_JOB,
            status=STARTED_STATUS,
            progress_current=3,
            progress_total=6,
        )
        self.get_error = None
        self.progress_error = None
        self.failure_error = None
        self.progress_with = None
        self.failed_error = None

    def get_job(self, _job_id):
        if self.get_error is not None:
            raise self.get_error
        return self.job

    def update_progress(self, _job_id, **values):
        if self.progress_error is not None:
            raise self.progress_error
        self.progress_with = values

    def mark_failure(self, _job_id, *, error):
        self.failed_error = error
        if self.failure_error is not None:
            raise self.failure_error
        return True


def execute_fixture(*, retries=0):
    context = FakeTaskContext(retries=retries)
    runner = FakeRunner()
    lock = FakeLock()
    tracker = FakeTracker()

    def execute():
        return execute_wikipedia_crawl_attempt(
            context,
            JOB_ID,
            runner_factory=lambda: runner,
            lock_factory=lambda: lock,
            tracker_factory=lambda: tracker,
        )

    return execute, context, runner, lock, tracker


def test_successful_execution_runs_once_under_uuid_advisory_lock():
    execute, _context, runner, lock, tracker = execute_fixture()

    result = execute()

    assert result == SUCCESS_RESULT
    assert runner.calls == [JOB_ID]
    assert lock.job_ids == [JOB_ID]
    assert tracker.failed_error is None


def test_busy_lock_ignores_duplicate_without_running_or_failing_real_job():
    execute, _context, runner, lock, tracker = execute_fixture()
    lock.acquired = False

    with pytest.raises(Ignore):
        execute()

    assert runner.calls == []
    assert tracker.failed_error is None


@pytest.mark.parametrize(
    "error",
    [
        OperationalError(
            "statement",
            {},
            ConnectionError("database unavailable"),
        ),
        RedisConnectionError("redis unavailable"),
        RedisTimeoutError("redis timed out"),
        WikipediaTransientError(
            "wikipedia_request_failed",
            attempts=3,
        ),
    ],
)
@pytest.mark.parametrize(("retries", "delay"), [(0, 2), (1, 4), (2, 8)])
def test_transient_errors_retry_with_backoff_and_preserved_progress(
    error,
    retries,
    delay,
):
    execute, context, runner, _lock, tracker = execute_fixture(
        retries=retries
    )
    runner.error = error

    with pytest.raises(FakeRetry):
        execute()

    assert context.retry_with == {"exc": error, "countdown": delay}
    assert tracker.progress_with == {
        "progress_current": 3,
        "progress_total": 6,
        "progress_message": "Temporary crawler failure; retrying",
    }
    assert tracker.failed_error is None


def test_retry_progress_error_never_replaces_original_transient_error():
    execute, context, runner, _lock, tracker = execute_fixture(retries=1)
    runner.error = WikipediaTransientError(
        "wikipedia_request_failed",
        attempts=3,
    )
    tracker.progress_error = RuntimeError("progress storage unavailable")

    with pytest.raises(FakeRetry):
        execute()

    assert context.retry_with["exc"] is runner.error


def test_exhausted_transient_failure_marks_stable_error_and_reraises():
    execute, context, runner, _lock, tracker = execute_fixture(retries=3)
    runner.error = RedisConnectionError("private redis connection detail")

    with pytest.raises(
        RedisConnectionError,
        match="private redis connection detail",
    ):
        execute()

    assert context.retry_with is None
    assert tracker.failed_error == "Wikipedia crawl failed."


@pytest.mark.parametrize(
    "error",
    [
        WikipediaCrawlCompletionError("wikipedia_crawl_no_articles"),
        ValueError("programming invariant failed"),
    ],
)
def test_permanent_and_programming_errors_do_not_retry_and_mark_failure(error):
    execute, context, runner, _lock, tracker = execute_fixture()
    runner.error = error

    with pytest.raises(type(error), match=str(error)):
        execute()

    assert context.retry_with is None
    assert tracker.failed_error == "Wikipedia crawl failed."


@pytest.mark.parametrize("job", [None, "wrong_type"])
def test_missing_or_misrouted_task_never_fails_another_job(job):
    execute, context, runner, _lock, tracker = execute_fixture()
    if job is None:
        tracker.job = None
    else:
        tracker.job.job_type = BULK_DOCUMENT_INGESTION_JOB
    runner.error = JobTransitionError(
        "Wikipedia crawl job is missing or invalid."
    )

    with pytest.raises(JobTransitionError, match="missing or invalid"):
        execute()

    assert context.retry_with is None
    assert tracker.failed_error is None


def test_failure_recording_error_does_not_replace_original_exception():
    execute, _context, runner, _lock, tracker = execute_fixture()
    runner.error = ValueError("original runner failure")
    tracker.failure_error = RuntimeError("failure storage unavailable")

    with pytest.raises(ValueError, match="original runner failure"):
        execute()


def test_internal_log_keeps_exc_info_while_public_failure_stays_safe(caplog):
    execute, _context, runner, _lock, tracker = execute_fixture()
    private_detail = "PRIVATE-INTERNAL-FAILURE-947"
    runner.error = RuntimeError(private_detail)
    caplog.set_level(logging.ERROR, logger="app.workers.wikipedia_tasks")

    with pytest.raises(RuntimeError, match=private_detail):
        execute()

    failure_records = [
        record
        for record in caplog.records
        if record.getMessage().startswith("Wikipedia crawl job")
    ]
    assert len(failure_records) == 1
    assert failure_records[0].exc_info is not None
    assert tracker.failed_error == "Wikipedia crawl failed."


def test_task_configuration_supports_worker_crash_redelivery():
    assert wikipedia_crawl_task.name == "wikipedia.crawl"
    assert wikipedia_crawl_task.acks_late is True
    assert wikipedia_crawl_task.reject_on_worker_lost is True
    assert wikipedia_crawl_task.max_retries == 3


def test_task_rejects_job_id_different_from_celery_task_id():
    with pytest.raises(RuntimeError, match="Celery task id does not match"):
        wikipedia_crawl_task.apply(
            args=[str(JOB_ID)],
            task_id=str(OTHER_JOB_ID),
            throw=True,
        )
