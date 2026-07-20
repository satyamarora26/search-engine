from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies import get_job_service
from app.main import create_app
from app.models.job import (
    FAILURE_STATUS,
    PENDING_STATUS,
    SEARCH_INDEX_REBUILD_JOB,
    STARTED_STATUS,
    Job,
)
from app.services.jobs import (
    JobEnqueueError,
    JobNotFoundError,
    JobStorageError,
)

JOB_ID = UUID("c241dbf0-2d4e-4b91-9ad7-ce097a543bbd")


def build_job(*, status: str = PENDING_STATUS) -> Job:
    return Job(
        id=JOB_ID,
        job_type=SEARCH_INDEX_REBUILD_JOB,
        status=status,
        progress_current=2 if status == STARTED_STATUS else 0,
        progress_total=4,
        progress_message=(
            "Building search index"
            if status == STARTED_STATUS
            else "Waiting for worker"
        ),
        error=(
            "Search index rebuild failed."
            if status == FAILURE_STATUS
            else None
        ),
        created_at=datetime(2026, 7, 21, 10, 0, tzinfo=UTC),
        started_at=(
            datetime(2026, 7, 21, 10, 1, tzinfo=UTC)
            if status == STARTED_STATUS
            else None
        ),
        updated_at=datetime(2026, 7, 21, 10, 1, tzinfo=UTC),
    )


class FakeJobService:
    def __init__(self) -> None:
        self.job = build_job()
        self.enqueue_error: Exception | None = None
        self.get_error: Exception | None = None
        self.requested_ids = []

    def enqueue_search_index_rebuild(self) -> Job:
        if self.enqueue_error:
            raise self.enqueue_error
        return self.job

    def get_job(self, job_id: UUID) -> Job:
        self.requested_ids.append(job_id)
        if self.get_error:
            raise self.get_error
        return self.job


def build_client(service: FakeJobService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_job_service] = lambda: service
    return TestClient(app)


def test_search_rebuild_returns_durable_job_id_and_status_url():
    response = build_client(FakeJobService()).post("/api/v1/search/rebuild")

    assert response.status_code == 202
    assert response.json() == {
        "job_id": str(JOB_ID),
        "status": "PENDING",
        "status_url": f"/api/v1/jobs/{JOB_ID}",
    }


def test_duplicate_rebuild_can_return_existing_started_job():
    service = FakeJobService()
    service.job = build_job(status=STARTED_STATUS)

    response = build_client(service).post("/api/v1/search/rebuild")

    assert response.status_code == 202
    assert response.json()["job_id"] == str(JOB_ID)
    assert response.json()["status"] == "STARTED"


def test_job_status_returns_postgresql_backed_progress():
    service = FakeJobService()
    service.job = build_job(status=STARTED_STATUS)

    response = build_client(service).get(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 200
    assert response.json()["job_id"] == str(JOB_ID)
    assert response.json()["progress"] == {
        "current": 2,
        "total": 4,
        "percentage": 50.0,
        "message": "Building search index",
    }
    assert service.requested_ids == [JOB_ID]


def test_failed_job_status_exposes_only_safe_stored_error():
    service = FakeJobService()
    service.job = build_job(status=FAILURE_STATUS)

    response = build_client(service).get(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 200
    assert response.json()["error"] == "Search index rebuild failed."


def test_unknown_job_returns_404():
    service = FakeJobService()
    service.get_error = JobNotFoundError(f"Job {JOB_ID} was not found.")

    response = build_client(service).get(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 404


def test_storage_and_broker_failures_return_safe_503():
    for error, expected in [
        (JobStorageError("Job storage unavailable."), "Job storage unavailable."),
        (
            JobEnqueueError("Could not enqueue background job."),
            "Could not enqueue background job.",
        ),
    ]:
        service = FakeJobService()
        service.enqueue_error = error
        response = build_client(service).post("/api/v1/search/rebuild")

        assert response.status_code == 503
        assert response.json()["detail"] == expected


def test_job_status_storage_failure_returns_503():
    service = FakeJobService()
    service.get_error = JobStorageError("Job storage unavailable.")

    response = build_client(service).get(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 503


def test_job_status_rejects_malformed_uuid():
    response = build_client(FakeJobService()).get("/api/v1/jobs/not-a-uuid")

    assert response.status_code == 422
