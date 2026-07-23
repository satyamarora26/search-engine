from uuid import UUID

from pydantic import BaseModel


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
