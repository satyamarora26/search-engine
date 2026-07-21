from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_wikipedia_category(value: str) -> str:
    stripped = value.strip()
    if not stripped or any(
        ord(char) < 32 or ord(char) == 127 for char in stripped
    ):
        raise ValueError(
            "category must be a non-empty title without control characters"
        )

    title = (
        stripped[len("category:") :].strip()
        if stripped.casefold().startswith("category:")
        else stripped
    )
    if not title:
        raise ValueError("category title must not be empty")

    parsed = urlsplit(title)
    if parsed.scheme or parsed.netloc or title.startswith("//"):
        raise ValueError("category must be a title, not a URL")

    canonical = f"Category:{title}"
    if len(canonical) > 255:
        raise ValueError(
            "canonical category title must be at most 255 characters"
        )
    return canonical


class WikipediaCrawlRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_default=True,
    )

    category: str = Field(
        default="Category:Featured articles",
        min_length=1,
        max_length=255,
    )
    max_articles: int = Field(default=100, ge=1, le=500)
    max_depth: int = Field(default=0, ge=0, le=2)

    @field_validator("category")
    @classmethod
    def canonicalize_category(cls, value: str) -> str:
        return normalize_wikipedia_category(value)


class WikipediaCrawlItemResponse(BaseModel):
    position: int
    wikipedia_page_id: int
    title: str
    url: str
    fetch_status: str
    ingestion_status: str | None
    document_id: int | None
    error: str | None


class WikipediaCrawlItemListResponse(BaseModel):
    job_id: UUID
    total_results: int
    limit: int
    offset: int
    items: list[WikipediaCrawlItemResponse]
