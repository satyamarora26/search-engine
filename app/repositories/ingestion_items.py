from dataclasses import dataclass
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.ingestion_item import (
    FAILED_ITEM_STATUS,
    IMPORTED_ITEM_STATUS,
    PENDING_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    TERMINAL_ITEM_STATUSES,
    IngestionItem,
)


@dataclass(frozen=True)
class IngestionCounts:
    received: int
    imported: int
    skipped: int
    failed: int


class IngestionItemRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def stage_many(
        self,
        job_id: UUID,
        payloads: list[JsonValue],
    ) -> list[IngestionItem]:
        items = [
            IngestionItem(
                job_id=job_id,
                position=position,
                payload=payload,
                status=PENDING_ITEM_STATUS,
            )
            for position, payload in enumerate(payloads)
        ]
        self.session.add_all(items)
        self.session.flush()
        return items

    def get_for_update(self, item_id: int) -> IngestionItem | None:
        statement = (
            select(IngestionItem)
            .where(IngestionItem.id == item_id)
            .with_for_update()
        )
        return self.session.scalars(statement).one_or_none()

    def list_pending_ids(self, job_id: UUID) -> list[int]:
        statement = (
            select(IngestionItem.id)
            .where(
                IngestionItem.job_id == job_id,
                IngestionItem.status == PENDING_ITEM_STATUS,
            )
            .order_by(IngestionItem.position.asc())
        )
        return list(self.session.scalars(statement).all())

    def mark_imported(
        self,
        item_id: int,
        *,
        document_id: int,
    ) -> IngestionItem | None:
        return self._mark(
            item_id,
            status=IMPORTED_ITEM_STATUS,
            document_id=document_id,
            error=None,
        )

    def mark_skipped(
        self,
        item_id: int,
        *,
        error: str,
    ) -> IngestionItem | None:
        return self._mark(
            item_id,
            status=SKIPPED_ITEM_STATUS,
            document_id=None,
            error=error,
        )

    def mark_failed(
        self,
        item_id: int,
        *,
        error: str,
    ) -> IngestionItem | None:
        return self._mark(
            item_id,
            status=FAILED_ITEM_STATUS,
            document_id=None,
            error=error,
        )

    def count_terminal(self, job_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(IngestionItem)
            .where(
                IngestionItem.job_id == job_id,
                IngestionItem.status.in_(TERMINAL_ITEM_STATUSES),
            )
        )
        return int(self.session.scalar(statement) or 0)

    def counts(self, job_id: UUID) -> IngestionCounts:
        statement = (
            select(IngestionItem.status, func.count(IngestionItem.id))
            .where(IngestionItem.job_id == job_id)
            .group_by(IngestionItem.status)
        )
        grouped = dict(self.session.execute(statement).all())
        return IngestionCounts(
            received=sum(grouped.values()),
            imported=grouped.get(IMPORTED_ITEM_STATUS, 0),
            skipped=grouped.get(SKIPPED_ITEM_STATUS, 0),
            failed=grouped.get(FAILED_ITEM_STATUS, 0),
        )

    def count_for_job(self, job_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(IngestionItem)
            .where(IngestionItem.job_id == job_id)
        )
        return int(self.session.scalar(statement) or 0)

    def list_for_job(
        self,
        job_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[IngestionItem]:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        if offset < 0:
            raise ValueError("offset cannot be negative.")

        statement = (
            select(IngestionItem)
            .where(IngestionItem.job_id == job_id)
            .order_by(IngestionItem.position.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(statement).all())

    def _mark(
        self,
        item_id: int,
        *,
        status: str,
        document_id: int | None,
        error: str | None,
    ) -> IngestionItem | None:
        statement = (
            update(IngestionItem)
            .where(
                IngestionItem.id == item_id,
                IngestionItem.status == PENDING_ITEM_STATUS,
            )
            .values(
                status=status,
                document_id=document_id,
                error=error,
                updated_at=func.now(),
            )
            .returning(IngestionItem)
        )
        return self.session.scalars(statement).one_or_none()
