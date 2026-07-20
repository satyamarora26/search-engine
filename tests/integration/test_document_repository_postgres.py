import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories.documents import DELETED_STATUS, DocumentRepository


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
    session = Session(bind=connection)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_repository_create_update_and_soft_delete_round_trip(db_session):
    repository = DocumentRepository(db_session)
    url = f"https://example.com/{uuid4()}"

    created_document = repository.create(
        title="Live Postgres Document",
        content="This document was written to real PostgreSQL.",
        url=url,
    )

    assert created_document.id is not None
    assert created_document.created_at is not None
    assert repository.get_active(created_document.id) is created_document

    updated_document = repository.update_active(
        created_document.id,
        title="Updated Live Postgres Document",
        content="This document was updated inside real PostgreSQL.",
        url=None,
    )

    assert updated_document is created_document
    assert updated_document.title == "Updated Live Postgres Document"
    assert updated_document.content == "This document was updated inside real PostgreSQL."
    assert updated_document.url is None

    deleted_document = repository.soft_delete(created_document.id)

    assert deleted_document is created_document
    assert deleted_document.status == DELETED_STATUS
    assert repository.get_active(created_document.id) is None


def test_repository_list_active_filters_deleted_rows_in_real_postgres(db_session):
    repository = DocumentRepository(db_session)
    active_document = repository.create(
        title="Active document",
        content="This document should appear in active listings.",
        url=f"https://example.com/{uuid4()}",
    )
    deleted_document = repository.create(
        title="Deleted document",
        content="This document should not appear in active listings.",
        url=f"https://example.com/{uuid4()}",
    )

    repository.soft_delete(deleted_document.id)

    active_ids = {
        document.id
        for document in repository.list_active(limit=100, offset=0)
    }

    assert active_document.id in active_ids
    assert deleted_document.id not in active_ids
