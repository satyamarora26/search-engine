import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.main import create_app
from app.services.search_index import SearchIndexService, get_search_index_service
from app.services.search_index_sync import get_synchronized_search_index_service


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

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def client(db_session):
    app = create_app()
    search_index = SearchIndexService()

    def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_search_index_service] = lambda: search_index
    app.dependency_overrides[
        get_synchronized_search_index_service
    ] = lambda: search_index
    return TestClient(app)


def test_document_writes_update_search_index_immediately(client):
    marker = f"instantindex{uuid4().hex}"

    create_response = client.post(
        "/api/v1/documents",
        json={
            "title": "Instant Index Document",
            "content": f"This document contains {marker}.",
            "url": f"https://example.com/{uuid4()}",
        },
    )

    assert create_response.status_code == 201
    document_id = create_response.json()["id"]

    search_response = client.get("/api/v1/search", params={"q": marker})

    assert search_response.status_code == 200
    assert search_response.json()["results"][0]["document_id"] == document_id

    updated_marker = f"updatedindex{uuid4().hex}"
    patch_response = client.patch(
        f"/api/v1/documents/{document_id}",
        json={"content": f"This updated document contains {updated_marker}."},
    )

    assert patch_response.status_code == 200
    assert client.get("/api/v1/search", params={"q": marker}).json()["total_results"] == 0
    assert (
        client.get("/api/v1/search", params={"q": updated_marker})
        .json()["results"][0]["document_id"]
        == document_id
    )

    delete_response = client.delete(f"/api/v1/documents/{document_id}")

    assert delete_response.status_code == 204
    assert (
        client.get("/api/v1/search", params={"q": updated_marker})
        .json()["total_results"]
        == 0
    )
