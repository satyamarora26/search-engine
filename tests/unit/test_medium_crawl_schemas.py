from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.medium_crawls import CrawlItemListResponse, MediumCrawlRequest

JOB_ID = UUID("0ea30c3d-273f-44cc-a43f-489c2ece940d")


def test_request_normalizes_publication_url_and_uses_bounded_defaults():
    request = MediumCrawlRequest(
        publication_url="https://medium.com/towards-data-science/",
    )

    assert request.publication_url == "https://medium.com/towards-data-science"
    assert request.max_articles == 100
    assert request.max_depth == 0


@pytest.mark.parametrize(
    "publication_url",
    [
        "",
        "   ",
        "http://medium.com/towards-data-science",
        "https://example.com/towards-data-science",
        "https://medium.com/p/article",
        "https://medium.com/@author/article",
        "https://user:password@medium.com/towards-data-science",
        "https://medium.com/towards-data-science?source=search",
        "https://medium.com/towards-data-science#comments",
        "https://medium.com/towards-data-science\x00",
    ],
)
def test_request_rejects_non_publication_or_unsafe_urls(publication_url):
    with pytest.raises(ValidationError):
        MediumCrawlRequest(publication_url=publication_url)


@pytest.mark.parametrize(
    "payload",
    [
        {"max_articles": 0},
        {"max_articles": 501},
        {"max_articles": True},
        {"max_depth": 1},
        {"max_depth": False},
        {"source": "medium"},
    ],
)
def test_request_rejects_invalid_bounds_and_unknown_fields(payload):
    with pytest.raises(ValidationError):
        MediumCrawlRequest.model_validate(payload)


def test_item_response_exposes_outcomes_without_content_or_html():
    response = CrawlItemListResponse.model_validate(
        {
            "job_id": JOB_ID,
            "total_results": 1,
            "limit": 100,
            "offset": 0,
            "items": [
                {
                    "position": 0,
                    "source_item_id": "article-1",
                    "title": "Information retrieval",
                    "url": "https://medium.com/towards-data-science/article-1",
                    "fetch_status": "fetched",
                    "ingestion_status": "imported",
                    "document_id": 81,
                    "error": None,
                }
            ],
        }
    )

    dumped = response.model_dump()
    assert "content" not in dumped["items"][0]
    assert "html" not in dumped["items"][0]
