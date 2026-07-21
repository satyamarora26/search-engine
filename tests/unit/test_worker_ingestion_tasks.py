from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from celery.exceptions import Ignore
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app.models.job import (
    BULK_DOCUMENT_INGESTION_JOB,
    SEARCH_INDEX_REBUILD_JOB,
    STARTED_STATUS,
)
from app.services.advisory_locks import (
    JobAlreadyRunningError,
    PostgresAdvisoryLock,
)
from app.services.job_tracker import JobTransitionError
from app.workers.ingestion_tasks import (
    bulk_ingest_documents_task,
    execute_bulk_ingestion_attempt,
)

JOB_ID = UUID("d46c43aa-2cd6-47f4-a653-c3274c8413f9")
OTHER_JOB_ID = UUID("3d19cc7a-4895-42f6-954c-fd562dadc75a")
SUCCESS_RESULT = {
    "received_count": 1,
    "imported_count": 1,
    "skipped_count": 0,
    "failed_count": 0,
    "index_rebuilt": True,
    "index_version": f"redis-{JOB_ID}",
}


class FakeConnection:
    def __init__(self, *, acquired: bool = True) -> None:
        self.acquired = acquired
        self.executed = []
        self.closed = False

    def scalar(self, statement, parameters):
        self.executed.append((str(statement), parameters))
        return self.acquired

    def execute(self, statement, parameters):
        self.executed.append((str(statement), parameters))

    def close(self) -> None:
        self.closed = True


def test_advisory_lock_uses_job_uuid_and_always_unlocks():
    connection = FakeConnection()
    lock = PostgresAdvisoryLock(connection_factory=lambda: connection)

    with lock.acquire(JOB_ID):
        assert connection.executed[0][0].startswith(
            "select pg_try_advisory_lock"
        )
        assert connection.executed[0][1] == {"key": str(JOB_ID)}

    assert connection.executed[-1][0].startswith(
        "select pg_advisory_unlock"
    )
    assert connection.closed is True


def test_advisory_lock_unlocks_when_protected_work_raises():
    connection = FakeConnection()
    lock = PostgresAdvisoryLock(connection_factory=lambda: connection)

    with pytest.raises(RuntimeError, match="worker failed"):
        with lock.acquire(JOB_ID):
            raise RuntimeError("worker failed")

    assert connection.executed[-1][0].startswith(
        "select pg_advisory_unlock"
    )
    assert connection.closed is True


def test_busy_advisory_lock_closes_without_unlocking_unowned_lock():
    connection = FakeConnection(acquired=False)
    lock = PostgresAdvisoryLock(connection_factory=lambda: connection)

    with pytest.raises(JobAlreadyRunningError, match="already running"):
        with lock.acquire(JOB_ID):
            pytest.fail("busy lock must not enter the protected block")

    assert len(connection.executed) == 1
    assert connection.closed is True


class FakeRetry(Exception):
    pass


class FakeTaskContext:
    def __init__(self, *, retries: int = 0) -> None:
        self.request = SimpleNamespace(retries=retries)
        self.max_retries = 3
        self.retry_with = None

    def retry(self, **values):
        self.retry_with = values
        raise FakeRetry()


class FakeRunner:
    def __init__(self) -> None:
        self.calls = []
        self.error = None

    def run(self, job_id: UUID):
        self.calls.append(job_id)
        if self.error is not None:
            raise self.error
        return SUCCESS_RESULT


class FakeLock:
    def __init__(self) -> None:
        self.acquired = True
        self.job_ids = []

    @contextmanager
    def acquire(self, job_id: UUID):
        self.job_ids.append(job_id)
        if not self.acquired:
            raise JobAlreadyRunningError(f"Job {job_id} is already running.")
        yield


class FakeTracker:
    def __init__(self) -> None:
        self.job = SimpleNamespace(
            id=JOB_ID,
            job_type=BULK_DOCUMENT_INGESTION_JOB,
            status=STARTED_STATUS,
            progress_current=1,
            progress_total=2,
        )
        self.get_error = None
        self.failure_error = None
        self.progress_message = None
        self.failed_error = None

    def get_job(self, job_id: UUID):
        if self.get_error is not None:
            raise self.get_error
        return self.job

    def update_progress(self, job_id: UUID, **values) -> None:
        self.progress_message = values["progress_message"]

    def mark_failure(self, job_id: UUID, *, error: str) -> bool:
        self.failed_error = error
        if self.failure_error is not None:
            raise self.failure_error
        return True


def execute_fixture(*, retries: int = 0):
    context = FakeTaskContext(retries=retries)
    runner = FakeRunner()
    lock = FakeLock()
    tracker = FakeTracker()

    def execute():
        return execute_bulk_ingestion_attempt(
            context,
            JOB_ID,
            runner_factory=lambda: runner,
            lock_factory=lambda: lock,
            tracker_factory=lambda: tracker,
        )

    return execute, context, runner, lock, tracker


def test_successful_attempt_runs_once_under_job_lock():
    execute, _, runner, lock, tracker = execute_fixture()

    result = execute()

    assert result == SUCCESS_RESULT
    assert runner.calls == [JOB_ID]
    assert lock.job_ids == [JOB_ID]
    assert tracker.failed_error is None


def test_busy_lock_ignores_duplicate_without_running_or_failing_job():
    execute, _, runner, lock, tracker = execute_fixture()
    lock.acquired = False

    with pytest.raises(Ignore):
        execute()

    assert runner.calls == []
    assert tracker.failed_error is None


@pytest.mark.parametrize(
    ("retries", "delay"),
    [(0, 2), (1, 4), (2, 8)],
)
def test_transient_error_retries_with_backoff_and_safe_progress(retries, delay):
    execute, context, runner, _, tracker = execute_fixture(retries=retries)
    runner.error = OperationalError(
        "statement",
        {},
        ConnectionError("database secret"),
    )

    with pytest.raises(FakeRetry):
        execute()

    assert context.retry_with["exc"] is runner.error
    assert context.retry_with["countdown"] == delay
    assert tracker.progress_message == "Temporary failure; retrying"
    assert tracker.failed_error is None


def test_retry_progress_failure_does_not_replace_transient_error():
    execute, context, runner, _, tracker = execute_fixture(retries=1)
    runner.error = OperationalError(
        "statement",
        {},
        ConnectionError("database unavailable"),
    )
    tracker.get_error = RuntimeError("progress storage unavailable")

    with pytest.raises(FakeRetry):
        execute()

    assert context.retry_with["exc"] is runner.error


def test_exhausted_transient_retry_marks_failure_and_reraises_original():
    execute, context, runner, _, tracker = execute_fixture(retries=3)
    runner.error = RedisConnectionError("redis password leaked")

    with pytest.raises(RedisConnectionError, match="password leaked"):
        execute()

    assert context.retry_with is None
    assert tracker.failed_error == "Bulk ingestion failed."


def test_permanent_error_does_not_retry_and_marks_failure():
    execute, context, runner, _, tracker = execute_fixture()
    runner.error = ValueError("invalid durable job")

    with pytest.raises(ValueError, match="invalid durable job"):
        execute()

    assert context.retry_with is None
    assert tracker.failed_error == "Bulk ingestion failed."


def test_misrouted_bulk_task_does_not_fail_active_rebuild_job():
    execute, context, runner, _, tracker = execute_fixture()
    tracker.job.job_type = SEARCH_INDEX_REBUILD_JOB
    runner.error = JobTransitionError(
        "Bulk ingestion job is missing or invalid."
    )

    with pytest.raises(JobTransitionError, match="missing or invalid"):
        execute()

    assert context.retry_with is None
    assert tracker.failed_error is None


def test_failure_recording_error_does_not_replace_original_exception():
    execute, _, runner, _, tracker = execute_fixture()
    runner.error = ValueError("original runner failure")
    tracker.failure_error = RuntimeError("failure storage unavailable")

    with pytest.raises(ValueError, match="original runner failure"):
        execute()


def test_task_configuration_supports_worker_crash_redelivery():
    assert bulk_ingest_documents_task.name == "documents.bulk_ingest"
    assert bulk_ingest_documents_task.acks_late is True
    assert bulk_ingest_documents_task.reject_on_worker_lost is True
    assert bulk_ingest_documents_task.max_retries == 3


def test_task_rejects_public_job_id_that_differs_from_celery_task_id():
    with pytest.raises(
        RuntimeError,
        match="Celery task id does not match durable job id",
    ):
        bulk_ingest_documents_task.apply(
            args=[str(JOB_ID)],
            task_id=str(OTHER_JOB_ID),
            throw=True,
        )
