from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.crawls import CrawlItemListResponse, CrawlItemResponse
from app.services.crawl_types import CrawlerPolicyError
from app.services.rss_adapter import normalize_rss_feed_url


class RssCrawlRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_default=True,
    )

    feed_url: str = Field(min_length=1, max_length=2048)
    max_articles: int = Field(default=100, ge=1, le=500)
    max_depth: int = Field(default=0, ge=0, le=0)

    @field_validator("feed_url")
    @classmethod
    def normalize_feed_url(cls, value: str) -> str:
        try:
            return normalize_rss_feed_url(value).canonical_url
        except CrawlerPolicyError as error:
            raise ValueError("feed_url must be a public HTTPS RSS or Atom feed") from error


__all__ = [
    "CrawlItemListResponse",
    "CrawlItemResponse",
    "RssCrawlRequest",
]
