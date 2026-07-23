from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.crawl_types import CrawlerPolicyError
from app.services.medium_adapter import normalize_medium_publication_url


class MediumCrawlRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_default=True,
    )

    publication_url: str = Field(min_length=1, max_length=2048)
    max_articles: int = Field(default=100, ge=1, le=500)
    max_depth: int = Field(default=0, ge=0, le=0)

    @field_validator("publication_url")
    @classmethod
    def normalize_publication_url(cls, value: str) -> str:
        try:
            return normalize_medium_publication_url(value).canonical_url
        except CrawlerPolicyError as error:
            raise ValueError("publication_url must be a public Medium publication") from error


class CrawlItemResponse(BaseModel):
    position: int
    source_item_id: str | None
    title: str | None
    url: str
    fetch_status: str
    ingestion_status: str | None
    document_id: int | None
    error: str | None


class CrawlItemListResponse(BaseModel):
    job_id: UUID
    total_results: int
    limit: int
    offset: int
    items: list[CrawlItemResponse]
