from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PENDING_ITEM_STATUS = "pending"
IMPORTED_ITEM_STATUS = "imported"
SKIPPED_ITEM_STATUS = "skipped"
FAILED_ITEM_STATUS = "failed"
TERMINAL_ITEM_STATUSES = (
    IMPORTED_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    FAILED_ITEM_STATUS,
)


class IngestionItem(Base):
    __tablename__ = "ingestion_items"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "position",
            name="ingestion_items_job_position_key",
        ),
        CheckConstraint(
            "position >= 0",
            name="ingestion_items_position_check",
        ),
        CheckConstraint(
            "status in ('pending', 'imported', 'skipped', 'failed')",
            name="ingestion_items_status_check",
        ),
        CheckConstraint(
            "(status = 'pending' and document_id is null and error is null) "
            "or (status = 'imported' and document_id is not null "
            "and error is null) "
            "or (status in ('skipped', 'failed') and document_id is null "
            "and error is not null)",
            name="ingestion_items_outcome_check",
        ),
        Index(
            "ingestion_items_job_status_position_idx",
            "job_id",
            "status",
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
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=PENDING_ITEM_STATUS,
    )
    document_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("documents.id"),
        nullable=True,
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
