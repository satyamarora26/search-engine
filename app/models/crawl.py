from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PENDING_FRONTIER_STATUS = "pending"
COMPLETED_FRONTIER_STATUS = "completed"
FAILED_FRONTIER_STATUS = "failed"
PENDING_FETCH_STATUS = "pending"
FETCHED_FETCH_STATUS = "fetched"
FAILED_FETCH_STATUS = "failed"


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        CheckConstraint(
            "max_articles between 1 and 500",
            name="crawl_runs_article_limit_check",
        ),
        CheckConstraint(
            "max_depth = 0",
            name="crawl_runs_depth_check",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    max_articles: Mapped[int] = mapped_column(Integer, nullable=False)
    max_depth: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    discovery_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    limit_reached: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CrawlFrontier(Base):
    __tablename__ = "crawl_frontier"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "locator",
            name="crawl_frontier_job_locator_key",
        ),
        CheckConstraint(
            "depth = 0",
            name="crawl_frontier_depth_check",
        ),
        CheckConstraint(
            "status in ('pending', 'completed', 'failed')",
            name="crawl_frontier_status_check",
        ),
        CheckConstraint(
            "(status in ('pending', 'completed') and error is null) or "
            "(status = 'failed' and error is not null)",
            name="crawl_frontier_outcome_check",
        ),
        Index(
            "crawl_frontier_job_status_depth_idx",
            "job_id",
            "status",
            "depth",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crawl_runs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    continuation: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=PENDING_FRONTIER_STATUS,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CrawlItem(Base):
    __tablename__ = "crawl_items"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "position",
            name="crawl_items_job_position_key",
        ),
        UniqueConstraint(
            "job_id",
            "canonical_url",
            name="crawl_items_job_canonical_key",
        ),
        UniqueConstraint(
            "ingestion_item_id",
            name="crawl_items_ingestion_item_key",
        ),
        CheckConstraint(
            "position >= 0",
            name="crawl_items_position_check",
        ),
        CheckConstraint(
            "fetch_attempts >= 0",
            name="crawl_items_attempts_check",
        ),
        CheckConstraint(
            "fetch_status in ('pending', 'fetched', 'failed')",
            name="crawl_items_status_check",
        ),
        CheckConstraint(
            "(fetch_status = 'pending' and ingestion_item_id is null "
            "and error is null and fetched_at is null) or "
            "(fetch_status = 'fetched' and ingestion_item_id is not null "
            "and error is null and fetched_at is not null) or "
            "(fetch_status = 'failed' and ingestion_item_id is null "
            "and error is not null and fetched_at is null)",
            name="crawl_items_outcome_check",
        ),
        Index(
            "crawl_items_job_status_position_idx",
            "job_id",
            "fetch_status",
            "position",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("crawl_runs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_item_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetch_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=PENDING_FETCH_STATUS,
    )
    fetch_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    ingestion_item_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("ingestion_items.id", ondelete="CASCADE"),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
