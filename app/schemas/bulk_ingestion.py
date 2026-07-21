from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
)


class BulkDocumentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[JsonValue] = Field(min_length=1, max_length=500)


class BulkDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str
    content: str
    url: str | None = None

    @field_validator("title", "content")
    @classmethod
    def strip_non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must be a non-empty string")
        if "\x00" in stripped:
            raise ValueError("must not contain null characters")
        return stripped

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if "\x00" in stripped:
            raise ValueError("must not contain null characters")
        return stripped or None


def format_item_validation_error(error: ValidationError) -> str:
    first = error.errors(include_url=False, include_context=False)[0]
    location = ".".join(str(part) for part in first["loc"]) or "item"
    message = str(first["msg"]).removeprefix("Value error, ")
    return f"{location}: {message}"[:300]


class IngestionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    status: str
    document_id: int | None
    error: str | None


class IngestionItemListResponse(BaseModel):
    job_id: UUID
    total_results: int
    limit: int
    offset: int
    items: list[IngestionItemResponse]
