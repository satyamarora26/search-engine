from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_medium_crawl_service
from app.main import create_app
from app.models.job import PENDING_STATUS, SEARCH_INDEX_RESOURCE
from app.services.crawl_types import CrawlItemView
from app.services.jobs import IndexJobConflictError, JobEnqueueError, JobStorageError
from app.services.medium_crawls import MediumCrawlNotFoundError

JOB_ID = UUID("0ea30c3d-273f-44cc-a43f-489c2ece940d")
ACTIVE_JOB_ID = UUID("3d19cc7a-4895-42f6-954c-fd562dadc75a")


class FakeMediumCrawlService:
    def __init__(self):
        self.job = SimpleNamespace(id=JOB_ID, status=PENDING_STATUS)
        self.enqueue_error = None
        self.list_error = None
        self.submitted = None
        self.listed_with = None
        self.total = 1
        self.items = [
            CrawlItemView(
                0,
                "article-1",
                "Information retrieval",
                "https://medium.com/towards-data-science/article-1",
                "fetched",
                "imported",
                81,
                None,
            )
        ]

    def enqueue_crawl(self, request):
        self.submitted = request
        if self.enqueue_error:
            raise self.enqueue_error
        return self.job

    def list_items(self, job_id, *, limit, offset):
        self.listed_with = {"job_id": job_id, "limit": limit, "offset": offset}
        if self.list_error:
            raise self.list_error
        return self.total, self.items


def build_client(service):
    app = create_app()
    app.dependency_overrides[get_medium_crawl_service] = lambda: service
    return TestClient(app)


def test_submit_returns_202_and_normalized_request():
    service = FakeMediumCrawlService()

    response = build_client(service).post(
        "/api/v1/crawls/medium",
        json={
            "publication_url": "https://medium.com/towards-data-science/",
            "max_articles": 25,
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": str(JOB_ID),
        "status": "PENDING",
        "status_url": f"/api/v1/jobs/{JOB_ID}",
    }
    assert service.submitted.model_dump() == {
        "publication_url": "https://medium.com/towards-data-science",
        "max_articles": 25,
        "max_depth": 0,
    }


def test_submit_maps_conflict_and_infrastructure_failures():
    service = FakeMediumCrawlService()
    active_job = SimpleNamespace(
        id=ACTIVE_JOB_ID,
        resource_key=SEARCH_INDEX_RESOURCE,
        status=PENDING_STATUS,
    )
    service.enqueue_error = IndexJobConflictError(active_job)

    response = build_client(service).post(
        "/api/v1/crawls/medium",
        json={"publication_url": "https://medium.com/towards-data-science"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "A search index job is already active.",
        "active_job_id": str(ACTIVE_JOB_ID),
        "status_url": f"/api/v1/jobs/{ACTIVE_JOB_ID}",
    }

    for error in (
        JobStorageError("Job storage unavailable."),
        JobEnqueueError("Could not enqueue background job."),
    ):
        service = FakeMediumCrawlService()
        service.enqueue_error = error
        response = build_client(service).post(
            "/api/v1/crawls/medium",
            json={"publication_url": "https://medium.com/towards-data-science"},
        )
        assert response.status_code == 503


@pytest.mark.parametrize(
    "payload",
    [
        {"publication_url": "http://medium.com/towards-data-science"},
        {"max_articles": 0},
        {"max_depth": 1},
        {"unknown": "field"},
    ],
)
def test_submit_rejects_invalid_request(payload):
    service = FakeMediumCrawlService()

    response = build_client(service).post(
        "/api/v1/crawls/medium",
        json=payload,
    )

    assert response.status_code == 422
    assert service.submitted is None


def test_items_are_paginated_and_exclude_content():
    service = FakeMediumCrawlService()

    response = build_client(service).get(
        f"/api/v1/crawls/medium/{JOB_ID}/items",
        params={"limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["source_item_id"] == "article-1"
    assert "content" not in response.json()["items"][0]
    assert "html" not in response.json()["items"][0]
    assert service.listed_with == {"job_id": JOB_ID, "limit": 10, "offset": 0}


def test_items_map_unknown_job_and_storage_failure():
    service = FakeMediumCrawlService()
    service.list_error = MediumCrawlNotFoundError("Medium crawl was not found.")
    response = build_client(service).get(f"/api/v1/crawls/medium/{JOB_ID}/items")
    assert response.status_code == 404

    service = FakeMediumCrawlService()
    service.list_error = JobStorageError("Job storage unavailable.")
    response = build_client(service).get(f"/api/v1/crawls/medium/{JOB_ID}/items")
    assert response.status_code == 503
