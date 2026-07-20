from uuid import UUID

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.schemas.jobs import JobStatusResponse
from app.services.jobs import JobEnqueueError, get_job_service
from app.services.search_index import SearchIndexService, get_search_index_service

TASK_ID = "c241dbf0-2d4e-4b91-9ad7-ce097a543bbd"


class EmptyScalarResult:
    def all(self):
        return []


class EmptySession:
    def scalars(self, statement):
        return EmptyScalarResult()


class FakeJobService:
    def __init__(self) -> None:
        self.enqueue_error: Exception | None = None
        self.requested_task_ids: list[str] = []

    def enqueue_search_index_rebuild(self) -> str:
        if self.enqueue_error:
            raise self.enqueue_error
        return TASK_ID

    def get_job_status(self, task_id: str) -> JobStatusResponse:
        self.requested_task_ids.append(task_id)
        return JobStatusResponse(
            task_id=UUID(task_id),
            status="SUCCESS",
            ready=True,
            successful=True,
            result={
                "index_version": f"redis-{task_id}",
                "document_count": 4,
            },
        )


def build_client(service: FakeJobService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_job_service] = lambda: service
    app.dependency_overrides[get_db_session] = EmptySession
    app.dependency_overrides[get_search_index_service] = SearchIndexService
    return TestClient(app)


def test_search_rebuild_enqueues_job_and_returns_202():
    client = build_client(FakeJobService())

    response = client.post("/api/v1/search/rebuild")

    assert response.status_code == 202
    assert response.json() == {
        "task_id": TASK_ID,
        "status": "PENDING",
        "status_url": f"/api/v1/jobs/{TASK_ID}",
    }


def test_search_rebuild_maps_broker_failure_to_503():
    service = FakeJobService()
    service.enqueue_error = JobEnqueueError("Could not enqueue background job.")
    client = build_client(service)

    response = client.post("/api/v1/search/rebuild")

    assert response.status_code == 503
    assert response.json()["detail"] == "Could not enqueue background job."


def test_job_status_returns_normalized_result():
    service = FakeJobService()
    client = build_client(service)

    response = client.get(f"/api/v1/jobs/{TASK_ID}")

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert response.json()["result"]["document_count"] == 4
    assert service.requested_task_ids == [TASK_ID]


def test_job_status_rejects_malformed_uuid():
    response = build_client(FakeJobService()).get("/api/v1/jobs/not-a-uuid")

    assert response.status_code == 422
