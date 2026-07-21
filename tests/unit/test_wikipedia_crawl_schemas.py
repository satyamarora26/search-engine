from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.wikipedia_crawls import (
    WikipediaCrawlItemListResponse,
    WikipediaCrawlRequest,
)

JOB_ID = UUID("0ea30c3d-273f-44cc-a43f-489c2ece940d")


def test_request_uses_canonical_bounded_defaults():
    request = WikipediaCrawlRequest()

    assert request.category == "Category:Featured articles"
    assert request.max_articles == 100
    assert request.max_depth == 0


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("Physics", "Category:Physics"),
        (" Category:Physics ", "Category:Physics"),
        ("category:Featured articles", "Category:Featured articles"),
    ],
)
def test_request_canonicalizes_category_names(raw, canonical):
    assert WikipediaCrawlRequest(category=raw).category == canonical


@pytest.mark.parametrize(
    "category",
    [
        "",
        "   ",
        "Category:   ",
        "https://en.wikipedia.org/wiki/Physics",
        "Physics\x00",
        "x" * 255,
    ],
)
def test_request_rejects_blank_url_and_control_character_categories(category):
    with pytest.raises(ValidationError):
        WikipediaCrawlRequest(category=category)


@pytest.mark.parametrize(
    "payload",
    [
        {"max_articles": 0},
        {"max_articles": 501},
        {"max_articles": True},
        {"max_depth": -1},
        {"max_depth": 3},
        {"max_depth": False},
        {"language": "fr"},
    ],
)
def test_request_rejects_out_of_scope_values_and_unknown_fields(payload):
    with pytest.raises(ValidationError):
        WikipediaCrawlRequest.model_validate(payload)


def test_item_report_contains_outcomes_without_content_or_html():
    response = WikipediaCrawlItemListResponse.model_validate(
        {
            "job_id": JOB_ID,
            "total_results": 1,
            "limit": 100,
            "offset": 0,
            "items": [
                {
                    "position": 0,
                    "wikipedia_page_id": 42,
                    "title": "Information retrieval",
                    "url": (
                        "https://en.wikipedia.org/wiki/Information_retrieval"
                    ),
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
