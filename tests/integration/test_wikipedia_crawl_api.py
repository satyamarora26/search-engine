from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_wikipedia_crawl_service
from app.main import create_app
from app.models.job import PENDING_STATUS, SEARCH_INDEX_RESOURCE
from app.services.jobs import (
    IndexJobConflictError,
    JobEnqueueError,
    JobStorageError,
)
from app.services.wikipedia_crawls import WikipediaCrawlNotFoundError
from app.services.wikipedia_types import CrawlItemView

JOB_ID = UUID("0ea30c3d-273f-44cc-a43f-489c2ece940d")
ACTIVE_JOB_ID = UUID("3d19cc7a-4895-42f6-954c-fd562dadc75a")


class FakeWikipediaCrawlService:
    def __init__(self) -> None:
        self.job = SimpleNamespace(id=JOB_ID, status=PENDING_STATUS)
        self.enqueue_error = None
        self.list_error = None
        self.submitted = None
        self.listed_with = None
        self.total = 2
        self.items = [
            CrawlItemView(
                position=0,
                wikipedia_page_id=42,
                title="Information retrieval",
                url="https://en.wikipedia.org/wiki/Information_retrieval",
                fetch_status="fetched",
                ingestion_status="imported",
                document_id=81,
                error=None,
            ),
            CrawlItemView(
                position=1,
                wikipedia_page_id=43,
                title="Missing article",
                url="https://en.wikipedia.org/wiki/Missing_article",
                fetch_status="failed",
                ingestion_status=None,
                document_id=None,
                error="wikipedia_not_found",
            ),
        ]

    def enqueue_crawl(self, request):
        self.submitted = request
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


def build_client(service: FakeWikipediaCrawlService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_wikipedia_crawl_service] = lambda: service
    return TestClient(app)


def test_submit_returns_202_job_contract():
    service = FakeWikipediaCrawlService()

    response = build_client(service).post(
        "/api/v1/crawls/wikipedia",
        json={"category": "Physics", "max_articles": 25, "max_depth": 1},
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": str(JOB_ID),
        "status": "PENDING",
        "status_url": f"/api/v1/jobs/{JOB_ID}",
    }
    assert service.submitted.model_dump() == {
        "category": "Category:Physics",
        "max_articles": 25,
        "max_depth": 1,
    }


def test_submit_maps_active_job_to_409():
    service = FakeWikipediaCrawlService()
    active_job = SimpleNamespace(
        id=ACTIVE_JOB_ID,
        resource_key=SEARCH_INDEX_RESOURCE,
        status=PENDING_STATUS,
    )
    service.enqueue_error = IndexJobConflictError(active_job)

    response = build_client(service).post(
        "/api/v1/crawls/wikipedia",
        json={},
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
def test_submit_maps_infrastructure_failure_to_safe_503(error):
    service = FakeWikipediaCrawlService()
    service.enqueue_error = error

    response = build_client(service).post(
        "/api/v1/crawls/wikipedia",
        json={},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == str(error)


@pytest.mark.parametrize(
    "payload",
    [
        {"max_articles": 0},
        {"max_articles": 501},
        {"max_depth": 3},
        {"language": "fr"},
        {"category": "https://example.com/category"},
    ],
)
def test_submit_rejects_invalid_or_unknown_request_fields(payload):
    service = FakeWikipediaCrawlService()

    response = build_client(service).post(
        "/api/v1/crawls/wikipedia",
        json=payload,
    )

    assert response.status_code == 422
    assert service.submitted is None


def test_item_report_is_paginated_and_omits_content_and_html():
    service = FakeWikipediaCrawlService()

    response = build_client(service).get(
        f"/api/v1/crawls/wikipedia/{JOB_ID}/items",
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
                "wikipedia_page_id": 42,
                "title": "Information retrieval",
                "url": "https://en.wikipedia.org/wiki/Information_retrieval",
                "fetch_status": "fetched",
                "ingestion_status": "imported",
                "document_id": 81,
                "error": None,
            },
            {
                "position": 1,
                "wikipedia_page_id": 43,
                "title": "Missing article",
                "url": "https://en.wikipedia.org/wiki/Missing_article",
                "fetch_status": "failed",
                "ingestion_status": None,
                "document_id": None,
                "error": "wikipedia_not_found",
            },
        ],
    }
    assert service.listed_with == {
        "job_id": JOB_ID,
        "limit": 20,
        "offset": 0,
    }
    assert all("content" not in item for item in response.json()["items"])
    assert all("html" not in item for item in response.json()["items"])


def test_item_report_maps_unknown_job_to_404():
    service = FakeWikipediaCrawlService()
    service.list_error = WikipediaCrawlNotFoundError(
        f"Wikipedia crawl job {JOB_ID} was not found."
    )

    response = build_client(service).get(
        f"/api/v1/crawls/wikipedia/{JOB_ID}/items"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        f"Wikipedia crawl job {JOB_ID} was not found."
    )


def test_item_report_maps_storage_failure_to_503():
    service = FakeWikipediaCrawlService()
    service.list_error = JobStorageError("Job storage unavailable.")

    response = build_client(service).get(
        f"/api/v1/crawls/wikipedia/{JOB_ID}/items"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Job storage unavailable."


def test_item_report_rejects_malformed_uuid():
    response = build_client(FakeWikipediaCrawlService()).get(
        "/api/v1/crawls/wikipedia/not-a-uuid/items"
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}],
)
def test_item_report_rejects_invalid_pagination(params):
    service = FakeWikipediaCrawlService()

    response = build_client(service).get(
        f"/api/v1/crawls/wikipedia/{JOB_ID}/items",
        params=params,
    )

    assert response.status_code == 422
    assert service.listed_with is None
