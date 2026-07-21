import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.job import (
    BULK_DOCUMENT_INGESTION_JOB,
    FAILURE_STATUS,
    PENDING_STATUS,
    SEARCH_INDEX_REBUILD_JOB,
    SEARCH_INDEX_RESOURCE,
    STARTED_STATUS,
    SUCCESS_STATUS,
    Job,
)
from app.repositories.jobs import JobRepository

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL tests",
    ),
]


@pytest.fixture
def db_session():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(Job))
    session.flush()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def create_pending(
    repository: JobRepository,
    job_id=None,
    *,
    job_type: str = SEARCH_INDEX_REBUILD_JOB,
) -> Job:
    return repository.create_pending(
        job_id or uuid4(),
        job_type=job_type,
        resource_key=SEARCH_INDEX_RESOURCE,
        progress_total=4,
        progress_message="Waiting for worker",
    )


def test_partial_unique_index_allows_only_one_active_search_resource_job(
    db_session,
):
    repository = JobRepository(db_session)
    create_pending(repository)

    with pytest.raises(IntegrityError):
        create_pending(
            repository,
            job_type=BULK_DOCUMENT_INGESTION_JOB,
        )


def test_terminal_job_allows_next_rebuild_and_cannot_be_overwritten(db_session):
    repository = JobRepository(db_session)
    first = create_pending(repository)

    started = repository.claim(
        first.id,
        progress_current=1,
        progress_total=4,
        progress_message="Loading documents",
    )
    assert started is not None and started.status == STARTED_STATUS

    completed = repository.mark_success(
        first.id,
        result={"index_version": f"redis-{first.id}", "document_count": 3},
        progress_total=4,
        progress_message="Search index rebuilt",
    )
    rejected_failure = repository.mark_failure(
        first.id,
        error="Must not replace success.",
    )
    second = create_pending(repository)

    assert completed is not None and completed.status == SUCCESS_STATUS
    assert completed.result["document_count"] == 3
    assert rejected_failure is None
    assert second.id != first.id


def test_failure_is_terminal_and_stores_only_caller_supplied_safe_error(db_session):
    repository = JobRepository(db_session)
    job = create_pending(repository)

    failed = repository.mark_failure(
        job.id,
        error="Search index rebuild failed.",
    )
    rejected_claim = repository.claim(
        job.id,
        progress_current=1,
        progress_total=4,
        progress_message="Loading documents",
    )

    assert failed is not None and failed.status == FAILURE_STATUS
    assert failed.error == "Search index rebuild failed."
    assert rejected_claim is None


def test_database_rejects_progress_beyond_known_total(db_session):
    invalid = Job(
        id=uuid4(),
        job_type=SEARCH_INDEX_REBUILD_JOB,
        status=PENDING_STATUS,
        progress_current=5,
        progress_total=4,
    )
    db_session.add(invalid)

    with pytest.raises(IntegrityError):
        db_session.flush()
