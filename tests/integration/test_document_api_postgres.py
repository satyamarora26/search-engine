import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.search import get_search_index_service
from app.core.config import get_settings
from app.db.session import get_db_session
from app.main import create_app
from app.services.search_index import SearchIndexService


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
    return TestClient(app)


def test_document_api_crud_flow_against_real_postgres(client):
    url = f"https://example.com/{uuid4()}"

    create_response = client.post(
        "/api/v1/documents",
        json={
            "title": "Live API Document",
            "content": "Created through the FastAPI document route.",
            "url": url,
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    document_id = created["id"]
    assert created["title"] == "Live API Document"
    assert created["url"] == url

    get_response = client.get(f"/api/v1/documents/{document_id}")

    assert get_response.status_code == 200
    assert get_response.json()["id"] == document_id

    list_response = client.get("/api/v1/documents", params={"limit": 100})

    assert list_response.status_code == 200
    listed_ids = {document["id"] for document in list_response.json()["documents"]}
    assert document_id in listed_ids

    patch_response = client.patch(
        f"/api/v1/documents/{document_id}",
        json={"title": "Updated Live API Document", "url": None},
    )

    assert patch_response.status_code == 200
    updated = patch_response.json()
    assert updated["title"] == "Updated Live API Document"
    assert updated["url"] is None

    delete_response = client.delete(f"/api/v1/documents/{document_id}")

    assert delete_response.status_code == 204
    assert client.get(f"/api/v1/documents/{document_id}").status_code == 404


def test_document_api_returns_conflict_for_duplicate_url_in_real_postgres(client):
    url = f"https://example.com/{uuid4()}"
    payload = {
        "title": "Duplicate URL",
        "content": "The URL should be unique.",
        "url": url,
    }

    first_response = client.post("/api/v1/documents", json=payload)
    second_response = client.post("/api/v1/documents", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == "Document URL already exists."
