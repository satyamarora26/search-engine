from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SEARCH_INDEX_REBUILD_JOB = "search_index_rebuild"
BULK_DOCUMENT_INGESTION_JOB = "bulk_document_ingestion"
WIKIPEDIA_CRAWL_JOB = "wikipedia_crawl"
MEDIUM_CRAWL_JOB = "medium_crawl"
SEARCH_INDEX_RESOURCE = "search_index"
PENDING_STATUS = "PENDING"
STARTED_STATUS = "STARTED"
SUCCESS_STATUS = "SUCCESS"
FAILURE_STATUS = "FAILURE"
ACTIVE_STATUSES = (PENDING_STATUS, STARTED_STATUS)
TERMINAL_STATUSES = (SUCCESS_STATUS, FAILURE_STATUS)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status in ('PENDING', 'STARTED', 'SUCCESS', 'FAILURE')",
            name="jobs_status_check",
        ),
        CheckConstraint(
            "progress_current >= 0",
            name="jobs_progress_current_check",
        ),
        CheckConstraint(
            "progress_total is null or progress_total > 0",
            name="jobs_progress_total_check",
        ),
        CheckConstraint(
            "progress_total is null or progress_current <= progress_total",
            name="jobs_progress_bounds_check",
        ),
        Index("jobs_status_created_at_idx", "status", "created_at"),
        Index(
            "jobs_one_active_resource_idx",
            "resource_key",
            unique=True,
            postgresql_where=text(
                "resource_key is not null "
                "and status in ('PENDING', 'STARTED')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=PENDING_STATUS,
    )
    progress_current: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default="0",
    )
    progress_total: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
