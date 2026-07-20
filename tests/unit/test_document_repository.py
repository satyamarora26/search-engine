import pytest
from sqlalchemy.dialects import postgresql

from app.models.document import Document
from app.repositories.documents import (
    ACTIVE_STATUS,
    DELETED_STATUS,
    DocumentRepository,
)


class FakeScalarResult:
    def __init__(
        self,
        one: Document | None = None,
        all_: list[Document] | None = None,
    ) -> None:
        self._one = one
        self._all = all_ if all_ is not None else []

    def one_or_none(self) -> Document | None:
        return self._one

    def all(self) -> list[Document]:
        return self._all


class FakeSession:
    def __init__(self, result: FakeScalarResult | None = None) -> None:
        self.result = result or FakeScalarResult()
        self.added: list[Document] = []
        self.flushed = False
        self.refreshed: list[Document] = []
        self.statements = []

    def add(self, instance: Document) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        self.flushed = True

    def refresh(self, instance: Document) -> None:
        self.refreshed.append(instance)

    def scalars(self, statement):
        self.statements.append(statement)
        return self.result


def compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_create_adds_active_document_and_flushes_before_returning():
    session = FakeSession()
    repository = DocumentRepository(session)

    document = repository.create(
        title="BM25 Ranking",
        content="BM25 scores documents with term saturation.",
        url="https://example.com/bm25",
    )

    assert document.title == "BM25 Ranking"
    assert document.content == "BM25 scores documents with term saturation."
    assert document.url == "https://example.com/bm25"
    assert document.status == ACTIVE_STATUS
    assert session.added == [document]
    assert session.flushed is True
    assert session.refreshed == [document]


def test_get_active_reads_by_id_and_filters_deleted_documents():
    expected_document = Document(id=10, title="Postgres", content="Storage")
    session = FakeSession(FakeScalarResult(one=expected_document))
    repository = DocumentRepository(session)

    document = repository.get_active(10)

    assert document is expected_document
    sql = compile_sql(session.statements[0])
    assert "FROM documents" in sql
    assert "documents.id = 10" in sql
    assert "documents.status = 'active'" in sql


def test_list_active_applies_status_filter_limit_offset_and_stable_order():
    expected_documents = [
        Document(id=1, title="First", content="One"),
        Document(id=2, title="Second", content="Two"),
    ]
    session = FakeSession(FakeScalarResult(all_=expected_documents))
    repository = DocumentRepository(session)

    documents = repository.list_active(limit=25, offset=50)

    assert documents == expected_documents
    sql = compile_sql(session.statements[0])
    assert "documents.status = 'active'" in sql
    assert "ORDER BY documents.id ASC" in sql
    assert "LIMIT 25" in sql
    assert "OFFSET 50" in sql


def test_list_active_rejects_invalid_pagination():
    repository = DocumentRepository(FakeSession())

    with pytest.raises(ValueError, match="limit must be at least 1"):
        repository.list_active(limit=0)

    with pytest.raises(ValueError, match="offset cannot be negative"):
        repository.list_active(offset=-1)


def test_update_active_changes_document_fields_and_refreshes():
    existing_document = Document(
        id=4,
        title="Old title",
        content="Old content",
        url="https://example.com/old",
        status=ACTIVE_STATUS,
    )
    session = FakeSession(FakeScalarResult(one=existing_document))
    repository = DocumentRepository(session)

    updated_document = repository.update_active(
        4,
        title="New title",
        content="New content",
        url=None,
    )

    assert updated_document is existing_document
    assert existing_document.title == "New title"
    assert existing_document.content == "New content"
    assert existing_document.url is None
    assert session.flushed is True
    assert session.refreshed == [existing_document]


def test_update_active_returns_none_when_document_is_missing():
    session = FakeSession(FakeScalarResult(one=None))
    repository = DocumentRepository(session)

    updated_document = repository.update_active(
        404,
        title="New title",
        content="New content",
        url=None,
    )

    assert updated_document is None
    assert session.flushed is False
    assert session.refreshed == []


def test_soft_delete_marks_active_document_deleted_and_flushes():
    existing_document = Document(
        id=7,
        title="Crawler",
        content="Wikipedia crawler document.",
        status=ACTIVE_STATUS,
    )
    session = FakeSession(FakeScalarResult(one=existing_document))
    repository = DocumentRepository(session)

    deleted_document = repository.soft_delete(7)

    assert deleted_document is existing_document
    assert existing_document.status == DELETED_STATUS
    assert session.flushed is True
    assert session.refreshed == [existing_document]


def test_soft_delete_returns_none_when_document_is_missing():
    session = FakeSession(FakeScalarResult(one=None))
    repository = DocumentRepository(session)

    deleted_document = repository.soft_delete(404)

    assert deleted_document is None
    assert session.flushed is False
    assert session.refreshed == []
