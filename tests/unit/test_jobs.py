from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.job import (
    PENDING_STATUS,
    SEARCH_INDEX_REBUILD_JOB,
    STARTED_STATUS,
    SUCCESS_STATUS,
    Job,
)
from app.schemas.jobs import JobStatusResponse
from app.services.jobs import (
    JobEnqueueError,
    JobNotFoundError,
    JobService,
    JobStorageError,
)

JOB_ID = UUID("c241dbf0-2d4e-4b91-9ad7-ce097a543bbd")


def build_job(*, status: str = PENDING_STATUS) -> Job:
    return Job(
        id=JOB_ID,
        job_type=SEARCH_INDEX_REBUILD_JOB,
        status=status,
        progress_current=2 if status == STARTED_STATUS else 0,
        progress_total=4,
        progress_message=(
            "Building search index"
            if status == STARTED_STATUS
            else "Waiting for worker"
        ),
        created_at=datetime(2026, 7, 21, 10, 0, tzinfo=UTC),
        started_at=(
            datetime(2026, 7, 21, 10, 1, tzinfo=UTC)
            if status == STARTED_STATUS
            else None
        ),
        updated_at=datetime(2026, 7, 21, 10, 1, tzinfo=UTC),
    )


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeTaskSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    def apply_async(self, *, args: list[str], task_id: str):
        self.calls.append({"args": args, "task_id": task_id})
        if self.error:
            raise self.error
        return object()


class FakeJobRepository:
    def __init__(self) -> None:
        self.active_results: list[Job | None] = [None]
        self.job: Job | None = None
        self.get_error: Exception | None = None
        self.create_error: Exception | None = None
        self.created_with = None
        self.failed_with = None

    def get_active(self, job_type: str) -> Job | None:
        if self.get_error:
            raise self.get_error
        return self.active_results.pop(0)

    def create_pending(self, job_id: UUID, **values) -> Job:
        if self.create_error:
            raise self.create_error
        self.created_with = {"job_id": job_id, **values}
        self.job = build_job()
        return self.job

    def get(self, job_id: UUID) -> Job | None:
        if self.get_error:
            raise self.get_error
        return self.job

    def mark_failure(self, job_id: UUID, *, error: str) -> Job | None:
        self.failed_with = {"job_id": job_id, "error": error}
        return self.job


def build_service(session, task, repository) -> JobService:
    return JobService(
        session,
        task,
        job_id_factory=lambda: JOB_ID,
        repository=repository,
    )


def test_enqueue_commits_job_then_sends_same_uuid_to_celery():
    session = FakeSession()
    task = FakeTaskSender()
    repository = FakeJobRepository()

    job = build_service(session, task, repository).enqueue_search_index_rebuild()

    assert job.id == JOB_ID
    assert session.commits == 1
    assert repository.created_with == {
        "job_id": JOB_ID,
        "job_type": SEARCH_INDEX_REBUILD_JOB,
        "progress_total": 4,
        "progress_message": "Waiting for worker",
    }
    assert task.calls == [{"args": [str(JOB_ID)], "task_id": str(JOB_ID)}]


def test_enqueue_returns_existing_active_job_without_sending_task():
    session = FakeSession()
    task = FakeTaskSender()
    repository = FakeJobRepository()
    existing = build_job(status=STARTED_STATUS)
    repository.active_results = [existing]

    job = build_service(session, task, repository).enqueue_search_index_rebuild()

    assert job is existing
    assert session.commits == 0
    assert task.calls == []


def test_unique_insert_race_returns_winning_active_job():
    session = FakeSession()
    repository = FakeJobRepository()
    winner = build_job(status=STARTED_STATUS)
    repository.active_results = [None, winner]
    repository.create_error = IntegrityError("unique", {}, Exception())

    job = build_service(
        session,
        FakeTaskSender(),
        repository,
    ).enqueue_search_index_rebuild()

    assert job is winner
    assert session.rollbacks == 1


def test_broker_failure_marks_job_failed_without_storing_raw_error():
    session = FakeSession()
    repository = FakeJobRepository()
    task = FakeTaskSender(ConnectionError("redis password leaked"))

    with pytest.raises(JobEnqueueError, match="Could not enqueue background job"):
        build_service(session, task, repository).enqueue_search_index_rebuild()

    assert repository.failed_with == {
        "job_id": JOB_ID,
        "error": "Could not enqueue background job.",
    }
    assert "password" not in repository.failed_with["error"]
    assert session.commits == 2


def test_get_unknown_job_raises_not_found():
    repository = FakeJobRepository()

    with pytest.raises(JobNotFoundError, match=str(JOB_ID)):
        build_service(
            FakeSession(),
            FakeTaskSender(),
            repository,
        ).get_job(JOB_ID)


def test_database_error_is_mapped_to_stable_storage_error():
    repository = FakeJobRepository()
    repository.get_error = SQLAlchemyError("database password leaked")

    with pytest.raises(JobStorageError, match="Job storage unavailable") as caught:
        build_service(
            FakeSession(),
            FakeTaskSender(),
            repository,
        ).get_job(JOB_ID)

    assert "password" not in str(caught.value)


def test_enqueue_database_failure_never_sends_celery_task():
    repository = FakeJobRepository()
    repository.get_error = SQLAlchemyError("database unavailable")
    task = FakeTaskSender()

    with pytest.raises(JobStorageError, match="Job storage unavailable"):
        build_service(FakeSession(), task, repository).enqueue_search_index_rebuild()

    assert task.calls == []


def test_status_response_derives_progress_and_readiness_from_job():
    response = JobStatusResponse.from_job(build_job(status=STARTED_STATUS))

    assert response.job_id == JOB_ID
    assert response.ready is False
    assert response.successful is False
    assert response.progress.current == 2
    assert response.progress.total == 4
    assert response.progress.percentage == 50.0
    assert response.progress.message == "Building search index"


def test_terminal_status_response_is_ready_and_preserves_structured_result():
    job = build_job()
    job.status = SUCCESS_STATUS
    job.progress_current = 4
    job.result = {"index_version": f"redis-{JOB_ID}", "document_count": 5}

    response = JobStatusResponse.from_job(job)

    assert response.ready is True
    assert response.successful is True
    assert response.result == job.result


def test_unknown_progress_total_has_no_percentage():
    job = build_job(status=STARTED_STATUS)
    job.progress_total = None

    assert JobStatusResponse.from_job(job).progress.percentage is None
