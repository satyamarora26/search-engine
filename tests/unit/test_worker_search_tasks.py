import pytest

from app.models.document import Document
from app.workers.search_tasks import (
    rebuild_search_index_snapshot,
    rebuild_search_index_snapshot_task,
)


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


def test_rebuild_task_derives_version_from_celery_task_id(monkeypatch):
    called_with: list[str] = []

    def fake_rebuild(index_version: str):
        called_with.append(index_version)
        return {"index_version": index_version, "document_count": 0}

    monkeypatch.setattr(
        "app.workers.search_tasks.rebuild_search_index_snapshot",
        fake_rebuild,
    )

    result = rebuild_search_index_snapshot_task.apply(task_id="task-123")

    assert result.successful() is True
    assert result.result == {
        "index_version": "redis-task-123",
        "document_count": 0,
    }
    assert called_with == ["redis-task-123"]


def test_rebuild_search_index_snapshot_task_has_stable_name():
    assert rebuild_search_index_snapshot_task.name == "search.rebuild_index_snapshot"
