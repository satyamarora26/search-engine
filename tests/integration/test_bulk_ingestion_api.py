from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_bulk_ingestion_service
from app.main import create_app
from app.models.ingestion_item import (
    FAILED_ITEM_STATUS,
    IMPORTED_ITEM_STATUS,
)
from app.models.job import PENDING_STATUS, SEARCH_INDEX_RESOURCE
from app.services.bulk_ingestion import BulkIngestionNotFoundError
from app.services.jobs import (
    IndexJobConflictError,
    JobEnqueueError,
    JobStorageError,
)

JOB_ID = UUID("d46c43aa-2cd6-47f4-a653-c3274c8413f9")
ACTIVE_JOB_ID = UUID("3d19cc7a-4895-42f6-954c-fd562dadc75a")
VALID_PAYLOAD = {
    "title": "BM25",
    "content": "Probabilistic text ranking.",
    "url": "https://example.com/bm25",
}
INVALID_PAYLOAD = {"title": "Missing content"}


class FakeBulkIngestionService:
    def __init__(self) -> None:
        self.job = SimpleNamespace(id=JOB_ID, status=PENDING_STATUS)
        self.enqueue_error = None
        self.list_error = None
        self.submitted = None
        self.listed_with = None
        self.total = 2
        self.items = [
            SimpleNamespace(
                position=0,
                status=IMPORTED_ITEM_STATUS,
                document_id=81,
                error=None,
                payload=VALID_PAYLOAD,
            ),
            SimpleNamespace(
                position=1,
                status=FAILED_ITEM_STATUS,
                document_id=None,
                error="content: Field required",
                payload=INVALID_PAYLOAD,
            ),
        ]

    def enqueue_documents(self, payloads):
        self.submitted = payloads
        if self.enqueue_error is not None:
            raise self.enqueue_error
        return self.job

    def list_items(self, job_id: UUID, *, limit: int, offset: int):
        self.listed_with = {
            "job_id": job_id,
            "limit": limit,
            "offset": offset,
        }
        if self.list_error is not None:
            raise self.list_error
        return self.total, self.items


def build_client(service: FakeBulkIngestionService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_bulk_ingestion_service] = lambda: service
    return TestClient(app)


def test_bulk_submit_returns_202_job_contract():
    service = FakeBulkIngestionService()

    response = build_client(service).post(
        "/api/v1/documents/bulk",
        json={"documents": [VALID_PAYLOAD, INVALID_PAYLOAD]},
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": str(JOB_ID),
        "status": "PENDING",
        "status_url": f"/api/v1/jobs/{JOB_ID}",
    }
    assert service.submitted == [VALID_PAYLOAD, INVALID_PAYLOAD]


def test_bulk_submit_maps_active_job_to_409():
    service = FakeBulkIngestionService()
    active_job = SimpleNamespace(
        id=ACTIVE_JOB_ID,
        resource_key=SEARCH_INDEX_RESOURCE,
        status=PENDING_STATUS,
    )
    service.enqueue_error = IndexJobConflictError(active_job)

    response = build_client(service).post(
        "/api/v1/documents/bulk",
        json={"documents": [VALID_PAYLOAD]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "A search index job is already active.",
        "active_job_id": str(ACTIVE_JOB_ID),
        "status_url": f"/api/v1/jobs/{ACTIVE_JOB_ID}",
    }


@pytest.mark.parametrize(
    "error",
    [
        JobStorageError("Job storage unavailable."),
        JobEnqueueError("Could not enqueue background job."),
    ],
)
def test_bulk_submit_maps_infrastructure_failure_to_safe_503(error):
    service = FakeBulkIngestionService()
    service.enqueue_error = error

    response = build_client(service).post(
        "/api/v1/documents/bulk",
        json={"documents": [VALID_PAYLOAD]},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == str(error)


@pytest.mark.parametrize(
    "documents",
    [[], [None] * 501],
    ids=["empty", "over-limit"],
)
def test_bulk_submit_rejects_invalid_envelope_size(documents):
    service = FakeBulkIngestionService()

    response = build_client(service).post(
        "/api/v1/documents/bulk",
        json={"documents": documents},
    )

    assert response.status_code == 422
    assert service.submitted is None


def test_bulk_submit_rejects_unknown_envelope_fields():
    response = build_client(FakeBulkIngestionService()).post(
        "/api/v1/documents/bulk",
        json={"documents": [VALID_PAYLOAD], "rebuild": True},
    )

    assert response.status_code == 422


def test_bulk_item_report_is_paginated_and_omits_raw_payloads():
    service = FakeBulkIngestionService()

    response = build_client(service).get(
        f"/api/v1/documents/bulk/{JOB_ID}/items",
        params={"limit": 20, "offset": 0},
    )

    assert response.status_code == 200
    assert response.json() == {
        "job_id": str(JOB_ID),
        "total_results": 2,
        "limit": 20,
        "offset": 0,
        "items": [
            {
                "position": 0,
                "status": "imported",
                "document_id": 81,
                "error": None,
            },
            {
                "position": 1,
                "status": "failed",
                "document_id": None,
                "error": "content: Field required",
            },
        ],
    }
    assert service.listed_with == {
        "job_id": JOB_ID,
        "limit": 20,
        "offset": 0,
    }
    assert all("payload" not in item for item in response.json()["items"])


def test_bulk_item_report_maps_unknown_job_to_404():
    service = FakeBulkIngestionService()
    service.list_error = BulkIngestionNotFoundError(
        f"Bulk ingestion job {JOB_ID} was not found."
    )

    response = build_client(service).get(
        f"/api/v1/documents/bulk/{JOB_ID}/items"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        f"Bulk ingestion job {JOB_ID} was not found."
    )


def test_bulk_item_report_maps_storage_failure_to_503():
    service = FakeBulkIngestionService()
    service.list_error = JobStorageError("Job storage unavailable.")

    response = build_client(service).get(
        f"/api/v1/documents/bulk/{JOB_ID}/items"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Job storage unavailable."


def test_bulk_item_report_rejects_malformed_uuid():
    response = build_client(FakeBulkIngestionService()).get(
        "/api/v1/documents/bulk/not-a-uuid/items"
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_bulk_item_report_rejects_invalid_pagination(params):
    service = FakeBulkIngestionService()

    response = build_client(service).get(
        f"/api/v1/documents/bulk/{JOB_ID}/items",
        params=params,
    )

    assert response.status_code == 422
    assert service.listed_with is None
