from uuid import UUID

import pytest

from app.models.document import Document
from app.workers.search_tasks import (
    execute_rebuild_search_index_job,
    rebuild_search_index_snapshot,
    rebuild_search_index_snapshot_task,
)

JOB_ID = "c241dbf0-2d4e-4b91-9ad7-ce097a543bbd"


class FakeScalarResult:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents

    def all(self) -> list[Document]:
        return self.documents


class FakeSession:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self.closed = False

    def scalars(self, statement):
        return FakeScalarResult(self.documents)

    def close(self) -> None:
        self.closed = True


class FakeSnapshotStore:
    def __init__(self) -> None:
        self.published = []

    def publish(self, snapshot) -> None:
        self.published.append(snapshot)


class FakeJobTracker:
    def __init__(
        self,
        *,
        claimed: bool = True,
        failure_error: Exception | None = None,
    ) -> None:
        self.claimed = claimed
        self.failure_error = failure_error
        self.calls = []

    def claim(self, job_id: UUID, **values) -> bool:
        self.calls.append(("claim", job_id, values))
        return self.claimed

    def update_progress(self, job_id: UUID, **values) -> None:
        self.calls.append(("progress", job_id, values))

    def mark_success(self, job_id: UUID, **values) -> None:
        self.calls.append(("success", job_id, values))

    def mark_failure(self, job_id: UUID, **values) -> bool:
        self.calls.append(("failure", job_id, values))
        if self.failure_error:
            raise self.failure_error
        return True


def test_rebuild_search_index_snapshot_publishes_documents_and_version():
    session = FakeSession(
        [
            Document(
                id=1,
                title="Worker BM25 Document",
                content="background indexing with celery",
                url="https://example.com/worker-bm25",
            ),
            Document(
                id=2,
                title="Worker TFIDF Document",
                content="background indexing with redis",
                url=None,
            ),
        ]
    )
    store = FakeSnapshotStore()

    status = rebuild_search_index_snapshot(
        "redis-task-123",
        session_factory=lambda: session,
        store_factory=lambda: store,
    )

    assert status == {
        "index_version": "redis-task-123",
        "document_count": 2,
    }
    assert store.published[0].index_version == "redis-task-123"
    assert [document.id for document in store.published[0].documents] == [1, 2]
    assert store.published[0].documents[1].url is None
    assert session.closed is True


def test_rebuild_search_index_snapshot_closes_session_when_rebuild_fails():
    class BrokenSession(FakeSession):
        def scalars(self, statement):
            raise RuntimeError("database failed")

    session = BrokenSession([])

    with pytest.raises(RuntimeError, match="database failed"):
        rebuild_search_index_snapshot(
            "redis-task-failure",
            session_factory=lambda: session,
            store_factory=FakeSnapshotStore,
        )

    assert session.closed is True


def test_rebuild_search_index_snapshot_closes_session_when_publish_fails():
    class BrokenStore:
        def publish(self, snapshot) -> None:
            raise ConnectionError("redis failed")

    session = FakeSession([])

    with pytest.raises(ConnectionError, match="redis failed"):
        rebuild_search_index_snapshot(
            "redis-task-failure",
            session_factory=lambda: session,
            store_factory=BrokenStore,
        )

    assert session.closed is True


def test_execute_rebuild_records_claim_progress_and_success():
    tracker = FakeJobTracker()

    def fake_rebuild(index_version, progress_callback=None, **kwargs):
        assert index_version == f"redis-{JOB_ID}"
        progress_callback(2, "Building search index")
        progress_callback(3, "Publishing search snapshot")
        return {"index_version": index_version, "document_count": 7}

    result = execute_rebuild_search_index_job(
        JOB_ID,
        JOB_ID,
        tracker_factory=lambda: tracker,
        rebuild=fake_rebuild,
    )

    assert result["document_count"] == 7
    assert [call[0] for call in tracker.calls] == [
        "claim",
        "progress",
        "progress",
        "success",
    ]
    assert tracker.calls[0][2] == {
        "progress_current": 1,
        "progress_total": 4,
        "progress_message": "Loading documents",
    }
    assert tracker.calls[-1][2]["progress_total"] == 4


def test_execute_rebuild_rejects_duplicate_delivery_before_work():
    tracker = FakeJobTracker(claimed=False)
    rebuild_called = False

    def fake_rebuild(*args, **kwargs):
        nonlocal rebuild_called
        rebuild_called = True

    with pytest.raises(RuntimeError, match="not pending"):
        execute_rebuild_search_index_job(
            JOB_ID,
            JOB_ID,
            tracker_factory=lambda: tracker,
            rebuild=fake_rebuild,
        )

    assert rebuild_called is False
    assert [call[0] for call in tracker.calls] == ["claim"]


def test_execute_rebuild_stores_safe_failure_and_reraises_original_error():
    tracker = FakeJobTracker()

    def broken_rebuild(*args, **kwargs):
        raise ConnectionError("redis password leaked")

    with pytest.raises(ConnectionError, match="redis password leaked"):
        execute_rebuild_search_index_job(
            JOB_ID,
            JOB_ID,
            tracker_factory=lambda: tracker,
            rebuild=broken_rebuild,
        )

    failure = tracker.calls[-1]
    assert failure[0] == "failure"
    assert failure[2]["error"] == "Search index rebuild failed."
    assert "password" not in failure[2]["error"]


def test_failure_tracking_error_does_not_replace_original_task_error():
    tracker = FakeJobTracker(failure_error=RuntimeError("postgres failed"))

    def broken_rebuild(*args, **kwargs):
        raise ConnectionError("redis failed")

    with pytest.raises(ConnectionError, match="redis failed"):
        execute_rebuild_search_index_job(
            JOB_ID,
            JOB_ID,
            tracker_factory=lambda: tracker,
            rebuild=broken_rebuild,
        )


def test_execute_rebuild_requires_matching_public_and_celery_ids():
    tracker = FakeJobTracker()

    with pytest.raises(RuntimeError, match="does not match"):
        execute_rebuild_search_index_job(
            JOB_ID,
            "different-task-id",
            tracker_factory=lambda: tracker,
        )

    assert tracker.calls == []


def test_rebuild_task_passes_matching_celery_and_job_ids(monkeypatch):
    called_with = []

    def fake_execute(job_id: str, celery_task_id: str):
        called_with.append((job_id, celery_task_id))
        return {"index_version": f"redis-{job_id}", "document_count": 0}

    monkeypatch.setattr(
        "app.workers.search_tasks.execute_rebuild_search_index_job",
        fake_execute,
    )

    result = rebuild_search_index_snapshot_task.apply(
        args=[JOB_ID],
        task_id=JOB_ID,
    )

    assert result.successful() is True
    assert result.result == {
        "index_version": f"redis-{JOB_ID}",
        "document_count": 0,
    }
    assert called_with == [(JOB_ID, JOB_ID)]


def test_rebuild_search_index_snapshot_task_has_stable_name():
    assert rebuild_search_index_snapshot_task.name == "search.rebuild_index_snapshot"
