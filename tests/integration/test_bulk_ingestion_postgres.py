from importlib import import_module
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ingestion_item import (
    FAILED_ITEM_STATUS,
    IMPORTED_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    IngestionItem,
)
from app.models.job import BULK_DOCUMENT_INGESTION_JOB, Job
from app.repositories.documents import DocumentRepository
from app.services.advisory_locks import (
    JobAlreadyRunningError,
    PostgresAdvisoryLock,
)
from app.services.document_ingestion import IngestionItemProcessor

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL tests",
    ),
]


def repository_type():
    return import_module(
        "app.repositories.ingestion_items"
    ).IngestionItemRepository


@pytest.fixture
def db_session():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def create_bulk_job(session: Session, item_count: int) -> Job:
    job = Job(
        id=uuid4(),
        job_type=BULK_DOCUMENT_INGESTION_JOB,
        progress_current=0,
        progress_total=item_count + 1,
    )
    session.add(job)
    session.flush()
    return job


def test_repository_stages_and_lists_raw_items_in_request_order(db_session):
    job = create_bulk_job(db_session, 3)
    repository = repository_type()(db_session)

    staged = repository.stage_many(
        job.id,
        [{"title": "First"}, 42, None],
    )
    pending_ids = repository.list_pending_ids(job.id)
    listed = repository.list_for_job(job.id, limit=2, offset=1)

    assert [item.position for item in staged] == [0, 1, 2]
    assert pending_ids == [item.id for item in staged]
    assert [(item.position, item.payload) for item in listed] == [
        (1, 42),
        (2, None),
    ]
    assert repository.count_for_job(job.id) == 3


def test_repository_persists_guarded_terminal_outcomes_and_counts(db_session):
    job = create_bulk_job(db_session, 3)
    repository = repository_type()(db_session)
    first, second, third = repository.stage_many(
        job.id,
        [{"title": "Imported"}, {"title": "Duplicate"}, {}],
    )
    document = DocumentRepository(db_session).create(
        title="Imported",
        content="Stored through the ingestion repository test.",
        url=f"https://example.com/{uuid4()}",
    )

    imported = repository.mark_imported(first.id, document_id=document.id)
    skipped = repository.mark_skipped(second.id, error="duplicate_url")
    failed = repository.mark_failed(
        third.id,
        error="content: Field required",
    )
    rejected = repository.mark_failed(first.id, error="must not overwrite")
    counts = repository.counts(job.id)

    assert imported is not None and imported.status == IMPORTED_ITEM_STATUS
    assert imported.document_id == document.id
    assert skipped is not None and skipped.status == SKIPPED_ITEM_STATUS
    assert failed is not None and failed.status == FAILED_ITEM_STATUS
    assert rejected is None
    assert counts.received == 3
    assert counts.imported == 1
    assert counts.skipped == 1
    assert counts.failed == 1
    assert repository.count_terminal(job.id) == 3


def test_database_rejects_negative_item_position(db_session):
    job = create_bulk_job(db_session, 1)
    db_session.add(
        IngestionItem(
            job_id=job.id,
            position=-1,
            payload={"title": "Invalid position"},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_advisory_lock_rejects_second_connection_until_release():
    job_id = uuid4()
    first = PostgresAdvisoryLock()
    second = PostgresAdvisoryLock()

    with first.acquire(job_id):
        with pytest.raises(JobAlreadyRunningError, match="already running"):
            with second.acquire(job_id):
                pytest.fail("second connection must not own the same job lock")

    with second.acquire(job_id):
        pass


def test_processor_imports_valid_and_url_less_documents(db_session):
    job = create_bulk_job(db_session, 2)
    first, second = repository_type()(db_session).stage_many(
        job.id,
        [
            {
                "title": "  PostgreSQL search  ",
                "content": "  Durable ingestion item.  ",
                "url": f"https://example.com/{uuid4()}",
            },
            {"title": "URL optional", "content": "This has no URL."},
        ],
    )
    first_id = first.id
    second_id = second.id
    processor = IngestionItemProcessor(session_factory=lambda: db_session)

    first_outcome = processor.process(first_id)
    second_outcome = processor.process(second_id)

    assert first_outcome.status == IMPORTED_ITEM_STATUS
    assert second_outcome.status == IMPORTED_ITEM_STATUS
    assert first_outcome.document_id is not None
    assert second_outcome.document_id is not None
    first_document = DocumentRepository(db_session).get_active(
        first_outcome.document_id
    )
    second_document = DocumentRepository(db_session).get_active(
        second_outcome.document_id
    )
    assert first_document is not None
    assert first_document.title == "PostgreSQL search"
    assert first_document.content == "Durable ingestion item."
    assert second_document is not None and second_document.url is None


def test_processor_marks_invalid_payload_failed_without_document(db_session):
    job = create_bulk_job(db_session, 1)
    [item] = repository_type()(db_session).stage_many(
        job.id,
        [{"title": "Missing content"}],
    )
    processor = IngestionItemProcessor(session_factory=lambda: db_session)

    outcome = processor.process(item.id)

    assert outcome.status == FAILED_ITEM_STATUS
    assert outcome.error == "content: Field required"
    assert outcome.document_id is None


def test_processor_recovers_from_duplicate_url_and_marks_item_skipped(db_session):
    duplicate_url = f"https://example.com/{uuid4()}"
    DocumentRepository(db_session).create(
        title="Existing",
        content="The first document owns this URL.",
        url=duplicate_url,
    )
    job = create_bulk_job(db_session, 1)
    [item] = repository_type()(db_session).stage_many(
        job.id,
        [
            {
                "title": "Duplicate",
                "content": "The insert must roll back only its savepoint.",
                "url": duplicate_url,
            }
        ],
    )
    job_id = job.id
    item_id = item.id
    processor = IngestionItemProcessor(session_factory=lambda: db_session)

    outcome = processor.process(item_id)

    assert outcome.status == SKIPPED_ITEM_STATUS
    assert outcome.error == "duplicate_url"
    persisted = repository_type()(db_session).list_for_job(
        job_id,
        limit=1,
        offset=0,
    )
    assert persisted[0].status == SKIPPED_ITEM_STATUS


def test_null_character_item_fails_without_rolling_back_valid_sibling(
    db_session,
):
    job = create_bulk_job(db_session, 2)
    invalid, valid = repository_type()(db_session).stage_many(
        job.id,
        [
            {
                "title": "Invalid\x00title",
                "content": "PostgreSQL text cannot store null characters.",
            },
            {
                "title": "Valid sibling",
                "content": "This document must still be imported.",
                "url": f"https://example.com/{uuid4()}",
            },
        ],
    )
    invalid_id = invalid.id
    valid_id = valid.id
    processor = IngestionItemProcessor(session_factory=lambda: db_session)

    invalid_outcome = processor.process(invalid_id)
    valid_outcome = processor.process(valid_id)

    assert invalid_outcome.status == FAILED_ITEM_STATUS
    assert invalid_outcome.error == (
        "title: must not contain null characters"
    )
    assert valid_outcome.status == IMPORTED_ITEM_STATUS
    assert valid_outcome.document_id is not None
