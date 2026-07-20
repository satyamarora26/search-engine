from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DocumentCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    url: str | None = None

    @field_validator("title", "content")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field cannot be blank")
        return stripped

    @field_validator("url")
    @classmethod
    def strip_optional_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DocumentUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    url: str | None = None

    @field_validator("title", "content")
    @classmethod
    def strip_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("field cannot be blank")
        return stripped

    @field_validator("url")
    @classmethod
    def strip_optional_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def require_at_least_one_change(self) -> "DocumentUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null.")
        if "content" in self.model_fields_set and self.content is None:
            raise ValueError("content cannot be null.")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str | None
    content: str
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    total_results: int
    limit: int
    offset: int
    documents: list[DocumentResponse]
