from app.models.document import Document
from app.workers.search_tasks import (
    WORKER_SEARCH_INDEX_SNAPSHOT_VERSION,
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


def test_rebuild_search_index_snapshot_builds_worker_local_index_from_documents():
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

    status = rebuild_search_index_snapshot(session_factory=lambda: session)

    assert status == {
        "index_version": WORKER_SEARCH_INDEX_SNAPSHOT_VERSION,
        "document_count": 2,
    }
    assert session.closed is True


def test_rebuild_search_index_snapshot_closes_session_when_rebuild_fails():
    class BrokenSession(FakeSession):
        def scalars(self, statement):
            raise RuntimeError("database failed")

    session = BrokenSession([])

    try:
        rebuild_search_index_snapshot(session_factory=lambda: session)
    except RuntimeError as error:
        assert str(error) == "database failed"
    else:
        raise AssertionError("Expected rebuild failure to be raised.")

    assert session.closed is True


def test_rebuild_search_index_snapshot_task_has_stable_name():
    assert rebuild_search_index_snapshot_task.name == "search.rebuild_index_snapshot"
