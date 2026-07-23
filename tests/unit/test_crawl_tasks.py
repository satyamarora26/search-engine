from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from celery.exceptions import Ignore
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.models.job import MEDIUM_CRAWL_JOB, RSS_CRAWL_JOB, STARTED_STATUS
from app.services.advisory_locks import JobAlreadyRunningError
from app.services.crawl_types import CrawlerTransientError
from app.workers.crawl_tasks import (
    crawl_medium_task,
    crawl_rss_task,
    execute_medium_crawl_attempt,
    execute_rss_crawl_attempt,
)

JOB_ID = UUID("ed8bff1d-6986-47ad-bad6-dd802e677ccc")


class FakeRetry(Exception):
    pass


class FakeTaskContext:
    def __init__(self, retries=0):
        self.request = SimpleNamespace(retries=retries)
        self.max_retries = 3
        self.retry_with = None

    def retry(self, **values):
        self.retry_with = values
        raise FakeRetry()


class FakeRunner:
    def __init__(self):
        self.error = None
        self.calls = []
        self.result = {"source": "medium"}

    def run(self, job_id):
        self.calls.append(job_id)
        if self.error:
            raise self.error
        return self.result


class FakeLock:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.calls = []

    @contextmanager
    def acquire(self, job_id):
        self.calls.append(job_id)
        if not self.acquired:
            raise JobAlreadyRunningError("busy")
        yield


class FakeTracker:
    def __init__(self):
        self.job = SimpleNamespace(
            id=JOB_ID,
            job_type=MEDIUM_CRAWL_JOB,
            status=STARTED_STATUS,
            progress_current=2,
            progress_total=5,
        )
        self.progress = None
        self.failure = None

    def get_job(self, _job_id):
        return self.job

    def update_progress(self, _job_id, **values):
        self.progress = values

    def mark_failure(self, _job_id, *, error):
        self.failure = error


def fixture(retries=0):
    context = FakeTaskContext(retries)
    runner = FakeRunner()
    lock = FakeLock()
    tracker = FakeTracker()
    result = execute_medium_crawl_attempt(
        context,
        JOB_ID,
        runner_factory=lambda: runner,
        lock_factory=lambda: lock,
        tracker_factory=lambda: tracker,
    )
    return result, context, runner, lock, tracker


def test_successful_medium_task_runs_under_advisory_lock():
    result, _context, runner, lock, tracker = fixture()

    assert result == {"source": "medium"}
    assert runner.calls == [JOB_ID]
    assert lock.calls == [JOB_ID]
    assert tracker.failure is None


def test_successful_rss_task_uses_the_generic_execution_lifecycle():
    context = FakeTaskContext()
    runner = FakeRunner()
    runner.result = {"source": "rss"}
    lock = FakeLock()
    tracker = FakeTracker()
    tracker.job.job_type = RSS_CRAWL_JOB

    result = execute_rss_crawl_attempt(
        context,
        JOB_ID,
        runner_factory=lambda: runner,
        lock_factory=lambda: lock,
        tracker_factory=lambda: tracker,
    )

    assert result == {"source": "rss"}
    assert runner.calls == [JOB_ID]
    assert lock.calls == [JOB_ID]
    assert tracker.failure is None


def test_busy_lock_is_ignored_without_failure():
    context = FakeTaskContext()
    runner = FakeRunner()
    lock = FakeLock(acquired=False)
    tracker = FakeTracker()

    with pytest.raises(Ignore):
        execute_medium_crawl_attempt(
            context,
            JOB_ID,
            runner_factory=lambda: runner,
            lock_factory=lambda: lock,
            tracker_factory=lambda: tracker,
        )

    assert runner.calls == []
    assert tracker.failure is None


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("statement", {}, ConnectionError("database")),
        RedisConnectionError("redis"),
        CrawlerTransientError("medium_request_failed", attempts=3),
    ],
)
def test_transient_errors_retry_and_preserve_progress(error):
    context = FakeTaskContext(retries=0)
    runner = FakeRunner()
    runner.error = error
    lock = FakeLock()
    tracker = FakeTracker()

    with pytest.raises(FakeRetry):
        execute_medium_crawl_attempt(
            context,
            JOB_ID,
            runner_factory=lambda: runner,
            lock_factory=lambda: lock,
            tracker_factory=lambda: tracker,
        )

    assert context.retry_with["exc"] is error
    assert context.retry_with["countdown"] == 2
    assert tracker.progress["progress_message"] == "Temporary crawler failure; retrying"


def test_task_configuration_and_id_guard_are_durable():
    assert crawl_medium_task.name == "crawl.medium"
    assert crawl_medium_task.acks_late is True
    assert crawl_medium_task.reject_on_worker_lost is True
    assert crawl_medium_task.max_retries == 3
    assert crawl_rss_task.name == "crawl.rss"
    assert crawl_rss_task.acks_late is True
    assert crawl_rss_task.reject_on_worker_lost is True
    assert crawl_rss_task.max_retries == 3

    with pytest.raises(RuntimeError, match="Celery task id does not match"):
        crawl_medium_task.apply(
            args=[str(JOB_ID)],
            task_id="other-job",
            throw=True,
        )
