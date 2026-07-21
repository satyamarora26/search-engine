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
