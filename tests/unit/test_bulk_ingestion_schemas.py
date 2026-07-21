from importlib import import_module
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models.ingestion_item import IngestionItem

JOB_ID = UUID("57d89fd9-4b92-468c-8cc4-640ce73ec4f1")


def schemas():
    return import_module("app.schemas.bulk_ingestion")


def test_envelope_accepts_raw_json_values_for_partial_worker_validation():
    payload = schemas().BulkDocumentsRequest.model_validate(
        {
            "documents": [
                {"title": "Valid", "content": "Search content"},
                {"title": "Missing content"},
                42,
                None,
            ]
        }
    )

    assert len(payload.documents) == 4
    assert payload.documents[2:] == [42, None]


@pytest.mark.parametrize("documents", [[], [{}] * 501])
def test_envelope_enforces_batch_size(documents):
    with pytest.raises(ValidationError):
        schemas().BulkDocumentsRequest.model_validate({"documents": documents})


def test_envelope_rejects_unknown_top_level_fields():
    with pytest.raises(ValidationError):
        schemas().BulkDocumentsRequest.model_validate(
            {"documents": [{}], "mode": "replace"}
        )


def test_item_validation_strips_text_and_blank_url():
    item = schemas().BulkDocumentInput.model_validate(
        {
            "title": "  BM25  ",
            "content": "  ranking content  ",
            "url": "  ",
        }
    )

    assert item.model_dump() == {
        "title": "BM25",
        "content": "ranking content",
        "url": None,
    }


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            {"title": "BM25", "content": "Ranking", "secret": "value"},
            "secret: Extra inputs are not permitted",
        ),
        (
            {"title": "BM25"},
            "content: Field required",
        ),
        (
            {"title": "  ", "content": "Ranking"},
            "title: must be a non-empty string",
        ),
        (
            {"title": "BM25\x00hidden", "content": "Ranking"},
            "title: must not contain null characters",
        ),
        (
            {
                "title": "BM25",
                "content": "Ranking",
                "url": "https://example.com/\x00hidden",
            },
            "url: must not contain null characters",
        ),
    ],
)
def test_item_validation_returns_deterministic_safe_reason(payload, reason):
    with pytest.raises(ValidationError) as caught:
        schemas().BulkDocumentInput.model_validate(payload)

    assert schemas().format_item_validation_error(caught.value) == reason


def test_item_validation_rejects_non_object_without_echoing_input():
    with pytest.raises(ValidationError) as caught:
        schemas().BulkDocumentInput.model_validate("secret payload")

    reason = schemas().format_item_validation_error(caught.value)

    assert reason.startswith("item: Input should be a valid dictionary")
    assert "secret payload" not in reason


def test_item_response_reads_only_public_outcome_fields():
    item = IngestionItem(
        job_id=JOB_ID,
        position=2,
        payload={"content": "private full content"},
        status="failed",
        error="content: Field required",
    )

    response = schemas().IngestionItemResponse.model_validate(item)

    assert response.model_dump() == {
        "position": 2,
        "status": "failed",
        "document_id": None,
        "error": "content: Field required",
    }
