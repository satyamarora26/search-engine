from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models.ingestion_item import (
    FAILED_ITEM_STATUS,
    IMPORTED_ITEM_STATUS,
    PENDING_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
)
from app.services.document_ingestion import (
    IngestionItemNotFoundError,
    IngestionItemProcessor,
)

ITEM_ID = 44


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.nested_transactions = 0
        self.closed = False

    def begin_nested(self):
        self.nested_transactions += 1
        return nullcontext()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeItemRepository:
    def __init__(self, item) -> None:
        self.item = item
        self.imported_with = None
        self.skipped_with = None
        self.failed_with = None

    def get_for_update(self, item_id: int):
        return self.item if self.item is not None and item_id == self.item.id else None

    def mark_imported(self, item_id: int, *, document_id: int):
        self.imported_with = {"item_id": item_id, "document_id": document_id}
        return self._finish(IMPORTED_ITEM_STATUS, document_id=document_id)

    def mark_skipped(self, item_id: int, *, error: str):
        self.skipped_with = {"item_id": item_id, "error": error}
        return self._finish(SKIPPED_ITEM_STATUS, error=error)

    def mark_failed(self, item_id: int, *, error: str):
        self.failed_with = {"item_id": item_id, "error": error}
        return self._finish(FAILED_ITEM_STATUS, error=error)

    def _finish(
        self,
        status: str,
        *,
        document_id: int | None = None,
        error: str | None = None,
    ):
        self.item.status = status
        self.item.document_id = document_id
        self.item.error = error
        return self.item


class FakeDocumentRepository:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.created_with = None

    def create(self, *, title: str, content: str, url: str | None):
        self.created_with = {"title": title, "content": content, "url": url}
        if self.error is not None:
            raise self.error
        return SimpleNamespace(id=81)


def ingestion_item(**values):
    defaults = {
        "id": ITEM_ID,
        "position": 3,
        "payload": {
            "title": "  Search indexing  ",
            "content": "  BM25 ranks documents.  ",
            "url": "  https://example.com/bm25  ",
        },
        "status": PENDING_ITEM_STATUS,
        "document_id": None,
        "error": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def integrity_error(constraint: str | None) -> IntegrityError:
    diagnostic = SimpleNamespace(constraint_name=constraint)
    original = SimpleNamespace(diag=diagnostic)
    return IntegrityError("INSERT INTO documents", {}, original)


def processor_fixture(*, item=None, document_error: Exception | None = None):
    session = FakeSession()
    item_repository = FakeItemRepository(item if item is not None else ingestion_item())
    document_repository = FakeDocumentRepository(error=document_error)
    processor = IngestionItemProcessor(
        session_factory=lambda: session,
        item_repository_factory=lambda given: item_repository,
        document_repository_factory=lambda given: document_repository,
    )
    return processor, session, item_repository, document_repository


def test_valid_item_creates_document_and_marks_imported():
    processor, session, items, documents = processor_fixture()

    outcome = processor.process(ITEM_ID)

    assert outcome.position == 3
    assert outcome.status == IMPORTED_ITEM_STATUS
    assert outcome.document_id == 81
    assert outcome.error is None
    assert documents.created_with == {
        "title": "Search indexing",
        "content": "BM25 ranks documents.",
        "url": "https://example.com/bm25",
    }
    assert items.imported_with == {"item_id": ITEM_ID, "document_id": 81}
    assert session.nested_transactions == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


def test_invalid_item_is_failed_without_inserting_document():
    item = ingestion_item(payload={"title": "Missing content"})
    processor, session, items, documents = processor_fixture(item=item)

    outcome = processor.process(ITEM_ID)

    assert outcome.status == FAILED_ITEM_STATUS
    assert outcome.error == "content: Field required"
    assert documents.created_with is None
    assert items.failed_with == {
        "item_id": ITEM_ID,
        "error": "content: Field required",
    }
    assert session.nested_transactions == 0
    assert session.commits == 1
    assert session.closed is True


def test_named_url_unique_violation_is_skipped():
    processor, session, items, _ = processor_fixture(
        document_error=integrity_error("documents_url_key")
    )

    outcome = processor.process(ITEM_ID)

    assert outcome.status == SKIPPED_ITEM_STATUS
    assert outcome.error == "duplicate_url"
    assert items.skipped_with == {
        "item_id": ITEM_ID,
        "error": "duplicate_url",
    }
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


def test_non_url_integrity_violation_is_safely_failed():
    processor, session, items, _ = processor_fixture(
        document_error=integrity_error("documents_title_check")
    )

    outcome = processor.process(ITEM_ID)

    assert outcome.status == FAILED_ITEM_STATUS
    assert outcome.error == "document_integrity_error"
    assert items.failed_with == {
        "item_id": ITEM_ID,
        "error": "document_integrity_error",
    }
    assert "documents_title_check" not in outcome.error
    assert session.commits == 1
    assert session.closed is True


def test_url_less_item_is_imported():
    item = ingestion_item(
        payload={"title": "No source", "content": "Still searchable."}
    )
    processor, _, _, documents = processor_fixture(item=item)

    outcome = processor.process(ITEM_ID)

    assert outcome.status == IMPORTED_ITEM_STATUS
    assert documents.created_with == {
        "title": "No source",
        "content": "Still searchable.",
        "url": None,
    }


def test_terminal_item_is_returned_without_writing_again():
    item = ingestion_item(status=IMPORTED_ITEM_STATUS, document_id=81)
    processor, session, items, documents = processor_fixture(item=item)

    outcome = processor.process(ITEM_ID)

    assert outcome.status == IMPORTED_ITEM_STATUS
    assert outcome.document_id == 81
    assert documents.created_with is None
    assert items.imported_with is None
    assert session.commits == 0
    assert session.rollbacks == 0
    assert session.closed is True


def test_unknown_item_rolls_back_and_raises_not_found():
    processor, session, _, _ = processor_fixture()

    with pytest.raises(
        IngestionItemNotFoundError,
        match=f"Ingestion item {ITEM_ID + 1} was not found",
    ):
        processor.process(ITEM_ID + 1)

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True


def test_operational_error_rolls_back_and_closes_session():
    original = OSError("database connection dropped")
    error = OperationalError("INSERT INTO documents", {}, original)
    processor, session, _, _ = processor_fixture(document_error=error)

    with pytest.raises(OperationalError):
        processor.process(ITEM_ID)

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True
