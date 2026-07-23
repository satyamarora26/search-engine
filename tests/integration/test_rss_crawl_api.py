from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies import get_rss_crawl_service
from app.main import create_app
from app.models.job import PENDING_STATUS
from app.services.crawl_types import CrawlItemView

JOB_ID = UUID("dd7fc5c3-1be5-4771-8db4-a49eb6a32e2b")


class FakeRssService:
    def __init__(self):
        self.submitted = None
        self.job = SimpleNamespace(id=JOB_ID, status=PENDING_STATUS)

    def enqueue_crawl(self, request):
        self.submitted = request
        return self.job

    def list_items(self, _job_id, *, limit, offset):
        return 1, [
            CrawlItemView(
                0,
                "entry-1",
                "Search ranking",
                "https://example.com/articles/search-ranking",
                "fetched",
                "imported",
                12,
                None,
            )
        ]


def client(service):
    app = create_app()
    app.dependency_overrides[get_rss_crawl_service] = lambda: service
    return TestClient(app)


def test_submit_and_list_rss_crawl():
    service = FakeRssService()
    response = client(service).post(
        "/api/v1/crawls/rss",
        json={"feed_url": "https://example.com/feed.xml", "max_articles": 3},
    )

    assert response.status_code == 202
    assert response.json()["job_id"] == str(JOB_ID)
    assert service.submitted.feed_url == "https://example.com/feed.xml"

    items = client(service).get(f"/api/v1/crawls/rss/{JOB_ID}/items")

    assert items.status_code == 200
    assert items.json()["items"][0]["title"] == "Search ranking"
