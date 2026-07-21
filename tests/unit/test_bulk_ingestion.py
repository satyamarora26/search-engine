from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.job import (
    BULK_DOCUMENT_INGESTION_JOB,
    PENDING_STATUS,
    SEARCH_INDEX_REBUILD_JOB,
    SEARCH_INDEX_RESOURCE,
)
from app.services.bulk_ingestion import (
    BulkIngestionNotFoundError,
    BulkIngestionService,
)
from app.services.jobs import (
    IndexJobConflictError,
    JobEnqueueError,
    JobStorageError,
)

JOB_ID = UUID("d46c43aa-2cd6-47f4-a653-c3274c8413f9")
ACTIVE_JOB_ID = UUID("3d19cc7a-4895-42f6-954c-fd562dadc75a")
VALID_PAYLOAD = {
    "title": "BM25",
    "content": "Probabilistic text ranking.",
    "url": "https://example.com/bm25",
}
INVALID_PAYLOAD = {"title": "Missing content"}


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeJobRepository:
    def __init__(self) -> None:
        self.active_results = [None]
        self.active_error = None
        self.create_error = None
        self.get_error = None
        self.failure_error = None
        self.job = None
        self.created_with = None
        self.failed_with = None

    def get_active_by_resource(self, resource_key: str):
        assert resource_key == SEARCH_INDEX_RESOURCE
        if self.active_error is not None:
            raise self.active_error
        if len(self.active_results) > 1:
            return self.active_results.pop(0)
        return self.active_results[0]

    def create_pending(self, job_id: UUID, **values):
        self.created_with = {"job_id": job_id, **values}
        if self.create_error is not None:
            raise self.create_error
        self.job = SimpleNamespace(
            id=job_id,
            status=PENDING_STATUS,
            **values,
        )
        return self.job

    def mark_failure(self, job_id: UUID, *, error: str):
        self.failed_with = {"job_id": job_id, "error": error}
        if self.failure_error is not None:
            raise self.failure_error
        return self.job

    def get(self, job_id: UUID):
        if self.get_error is not None:
            raise self.get_error
        if self.job is not None and self.job.id == job_id:
            return self.job
        return None


class FakeItemRepository:
    def __init__(self) -> None:
        self.stage_error = None
        self.count_error = None
        self.list_error = None
        self.staged_with = None
        self.total = 0
        self.listed = []
        self.listed_with = None

    def stage_many(self, job_id: UUID, payloads):
        self.staged_with = {"job_id": job_id, "payloads": payloads}
        if self.stage_error is not None:
            raise self.stage_error
        return []

    def count_for_job(self, job_id: UUID) -> int:
        if self.count_error is not None:
            raise self.count_error
        return self.total

    def list_for_job(self, job_id: UUID, *, limit: int, offset: int):
        self.listed_with = {
            "job_id": job_id,
            "limit": limit,
            "offset": offset,
        }
        if self.list_error is not None:
            raise self.list_error
        return self.listed


class FakeTask:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.error = None
        self.calls = []
        self.commits_when_called = []

    def apply_async(self, *, args: list[str], task_id: str):
        self.commits_when_called.append(self.session.commits)
        self.calls.append({"args": args, "task_id": task_id})
        if self.error is not None:
            raise self.error


def active_job(*, job_type: str = SEARCH_INDEX_REBUILD_JOB):
    return SimpleNamespace(
        id=ACTIVE_JOB_ID,
        job_type=job_type,
        resource_key=SEARCH_INDEX_RESOURCE,
        status=PENDING_STATUS,
    )


def service_fixture():
    session = FakeSession()
    jobs = FakeJobRepository()
    items = FakeItemRepository()
    task = FakeTask(session)
    service = BulkIngestionService(
        session,
        task,
        job_id_factory=lambda: JOB_ID,
        job_repository=jobs,
        item_repository=items,
    )
    return service, session, jobs, items, task


def test_enqueue_commits_job_and_items_before_sending_only_job_id():
    service, session, jobs, items, task = service_fixture()

    job = service.enqueue_documents([VALID_PAYLOAD, INVALID_PAYLOAD])

    assert job.id == JOB_ID
    assert session.commits == 1
    assert jobs.created_with == {
        "job_id": JOB_ID,
        "job_type": BULK_DOCUMENT_INGESTION_JOB,
        "resource_key": SEARCH_INDEX_RESOURCE,
        "progress_total": 3,
        "progress_message": "Waiting for worker",
    }
    assert items.staged_with == {
        "job_id": JOB_ID,
        "payloads": [VALID_PAYLOAD, INVALID_PAYLOAD],
    }
    assert task.calls == [{"args": [str(JOB_ID)], "task_id": str(JOB_ID)}]
    assert task.commits_when_called == [1]


def test_active_resource_rejects_new_batch_without_staging():
    service, session, jobs, items, task = service_fixture()
    running_job = active_job()
    jobs.active_results = [running_job]

    with pytest.raises(IndexJobConflictError) as caught:
        service.enqueue_documents([VALID_PAYLOAD])

    assert caught.value.active_job is running_job
    assert items.staged_with is None
    assert jobs.created_with is None
    assert task.calls == []
    assert session.commits == 0


def test_unique_resource_race_reports_winning_job():
    service, session, jobs, items, task = service_fixture()
    winner = active_job(job_type=BULK_DOCUMENT_INGESTION_JOB)
    jobs.active_results = [None, winner]
    jobs.create_error = IntegrityError("INSERT INTO jobs", {}, Exception())

    with pytest.raises(IndexJobConflictError) as caught:
        service.enqueue_documents([VALID_PAYLOAD])

    assert caught.value.active_job is winner
    assert session.rollbacks == 1
    assert items.staged_with is None
    assert task.calls == []


def test_unique_resource_race_without_winner_maps_to_storage_error():
    service, session, jobs, _, _ = service_fixture()
    jobs.active_results = [None, None]
    jobs.create_error = IntegrityError("INSERT INTO jobs", {}, Exception())

    with pytest.raises(JobStorageError, match="Job storage unavailable"):
        service.enqueue_documents([VALID_PAYLOAD])

    assert session.rollbacks == 1


def test_database_failure_rolls_back_and_maps_to_safe_storage_error():
    service, session, _, items, task = service_fixture()
    items.stage_error = SQLAlchemyError("database hostname leaked")

    with pytest.raises(JobStorageError, match="Job storage unavailable") as caught:
        service.enqueue_documents([VALID_PAYLOAD])

    assert "hostname" not in str(caught.value)
    assert session.rollbacks == 1
    assert task.calls == []


def test_broker_failure_marks_job_failed_with_safe_message():
    service, session, jobs, _, task = service_fixture()
    task.error = ConnectionError("redis password leaked")

    with pytest.raises(JobEnqueueError, match="Could not enqueue") as caught:
        service.enqueue_documents([VALID_PAYLOAD])

    assert "password" not in str(caught.value)
    assert jobs.failed_with == {
        "job_id": JOB_ID,
        "error": "Could not enqueue background job.",
    }
    assert session.commits == 2


def test_failure_to_record_broker_error_does_not_replace_enqueue_error():
    service, session, jobs, _, task = service_fixture()
    task.error = ConnectionError("redis unavailable")
    jobs.failure_error = SQLAlchemyError("postgres unavailable")

    with pytest.raises(JobEnqueueError, match="Could not enqueue"):
        service.enqueue_documents([VALID_PAYLOAD])

    assert session.commits == 1
    assert session.rollbacks == 1


def test_list_items_returns_total_and_stable_repository_page():
    service, _, jobs, items, _ = service_fixture()
    jobs.job = SimpleNamespace(id=JOB_ID, job_type=BULK_DOCUMENT_INGESTION_JOB)
    items.total = 3
    items.listed = [
        SimpleNamespace(position=1),
        SimpleNamespace(position=2),
    ]

    total, listed = service.list_items(JOB_ID, limit=2, offset=1)

    assert total == 3
    assert [item.position for item in listed] == [1, 2]
    assert items.listed_with == {
        "job_id": JOB_ID,
        "limit": 2,
        "offset": 1,
    }


@pytest.mark.parametrize(
    "job",
    [
        None,
        SimpleNamespace(id=JOB_ID, job_type=SEARCH_INDEX_REBUILD_JOB),
    ],
)
def test_list_items_rejects_unknown_or_non_bulk_job(job):
    service, _, jobs, _, _ = service_fixture()
    jobs.job = job

    with pytest.raises(
        BulkIngestionNotFoundError,
        match=f"Bulk ingestion job {JOB_ID} was not found",
    ):
        service.list_items(JOB_ID, limit=100, offset=0)


def test_list_items_maps_database_failure_to_storage_error():
    service, session, jobs, items, _ = service_fixture()
    jobs.job = SimpleNamespace(id=JOB_ID, job_type=BULK_DOCUMENT_INGESTION_JOB)
    items.count_error = SQLAlchemyError("database hostname leaked")

    with pytest.raises(JobStorageError, match="Job storage unavailable"):
        service.list_items(JOB_ID, limit=100, offset=0)

    assert session.rollbacks == 1
