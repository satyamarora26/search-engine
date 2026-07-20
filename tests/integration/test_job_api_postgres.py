import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.api.dependencies import get_job_service
from app.core.config import get_settings
from app.main import create_app
from app.models.job import Job
from app.repositories.jobs import JobRepository
from app.services.jobs import JobService

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL tests",
    ),
]


class FakeTaskSender:
    def __init__(self) -> None:
        self.calls = []

    def apply_async(self, *, args: list[str], task_id: str):
        self.calls.append({"args": args, "task_id": task_id})
        return object()


@pytest.fixture
def db_session():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(Job))
    session.commit()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def client_and_task(db_session):
    task = FakeTaskSender()
    service = JobService(db_session, task)
    app = create_app()
    app.dependency_overrides[get_job_service] = lambda: service
    return TestClient(app), task, db_session


def test_rebuild_and_status_round_trip_against_postgresql(client_and_task):
    client, task, db_session = client_and_task

    accepted = client.post("/api/v1/search/rebuild")
    job_id = UUID(accepted.json()["job_id"])
    duplicate = client.post("/api/v1/search/rebuild")
    status = client.get(f"/api/v1/jobs/{job_id}")

    assert accepted.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json()["job_id"] == str(job_id)
    assert task.calls == [{"args": [str(job_id)], "task_id": str(job_id)}]
    assert status.status_code == 200
    assert status.json()["status"] == "PENDING"
    assert JobRepository(db_session).get(job_id) is not None


def test_unknown_job_is_real_404_against_postgresql(client_and_task):
    client, _, _ = client_and_task

    response = client.get(f"/api/v1/jobs/{uuid4()}")

    assert response.status_code == 404
