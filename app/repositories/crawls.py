from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.crawl import (
    COMPLETED_FRONTIER_STATUS,
    FAILED_FETCH_STATUS,
    FAILED_FRONTIER_STATUS,
    FETCHED_FETCH_STATUS,
    PENDING_FETCH_STATUS,
    PENDING_FRONTIER_STATUS,
    CrawlFrontier,
    CrawlItem,
    CrawlRun,
)
from app.models.ingestion_item import (
    FAILED_ITEM_STATUS,
    IMPORTED_ITEM_STATUS,
    PENDING_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    IngestionItem,
)
from app.services.crawl_types import (
    CrawlCounts,
    CrawlItemView,
    CrawlRunSnapshot,
    DiscoveryCheckpoint,
    DiscoveredItem,
    FrontierSnapshot,
)


class CrawlRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(
        self,
        job_id: UUID,
        *,
        source_key: str,
        seed_url: str,
        max_articles: int,
        max_depth: int,
    ) -> CrawlRun:
        run = CrawlRun(
            job_id=job_id,
            source_key=source_key,
            seed_url=seed_url,
            max_articles=max_articles,
            max_depth=max_depth,
            discovery_complete=False,
            limit_reached=False,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def add_frontier(
        self,
        job_id: UUID,
        *,
        locator: str,
        depth: int,
        continuation: dict[str, Any] | None = None,
    ) -> CrawlFrontier:
        frontier = CrawlFrontier(
            job_id=job_id,
            locator=locator,
            depth=depth,
            continuation=continuation,
            status=PENDING_FRONTIER_STATUS,
            error=None,
        )
        self.session.add(frontier)
        self.session.flush()
        return frontier

    def get_run(self, job_id: UUID) -> CrawlRunSnapshot | None:
        model = self.session.scalars(
            select(CrawlRun).where(CrawlRun.job_id == job_id)
        ).one_or_none()
        return self._run_snapshot(model) if model is not None else None

    def get_run_for_update(self, job_id: UUID) -> CrawlRun | None:
        statement = (
            select(CrawlRun)
            .where(CrawlRun.job_id == job_id)
            .with_for_update()
        )
        return self.session.scalars(statement).one_or_none()

    def get_frontier_for_update(
        self,
        frontier_id: int,
    ) -> CrawlFrontier | None:
        statement = (
            select(CrawlFrontier)
            .where(CrawlFrontier.id == frontier_id)
            .with_for_update()
        )
        return self.session.scalars(statement).one_or_none()

    def get_next_pending_frontier(
        self,
        job_id: UUID,
    ) -> FrontierSnapshot | None:
        statement = (
            select(CrawlFrontier)
            .where(
                CrawlFrontier.job_id == job_id,
                CrawlFrontier.status == PENDING_FRONTIER_STATUS,
            )
            .order_by(
                CrawlFrontier.depth.asc(),
                CrawlFrontier.id.asc(),
            )
            .limit(1)
        )
        model = self.session.scalars(statement).one_or_none()
        return self._frontier_snapshot(model) if model is not None else None

    def add_item(
        self,
        job_id: UUID,
        *,
        position: int,
        discovered_item: DiscoveredItem,
    ) -> CrawlItem:
        item = CrawlItem(
            job_id=job_id,
            position=position,
            source_item_id=discovered_item.source_item_id,
            discovered_url=discovered_item.discovered_url,
            canonical_url=discovered_item.canonical_url,
            title=discovered_item.title,
            fetch_status=PENDING_FETCH_STATUS,
            fetch_attempts=0,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def get_item_for_update(self, item_id: int) -> CrawlItem | None:
        statement = (
            select(CrawlItem)
            .where(CrawlItem.id == item_id)
            .with_for_update()
        )
        return self.session.scalars(statement).one_or_none()

    def mark_item_fetched(
        self,
        item_id: int,
        *,
        attempts: int,
        ingestion_item_id: int,
        fetched_at: datetime,
    ) -> CrawlItem | None:
        statement = (
            update(CrawlItem)
            .where(
                CrawlItem.id == item_id,
                CrawlItem.fetch_status == PENDING_FETCH_STATUS,
            )
            .values(
                fetch_status=FETCHED_FETCH_STATUS,
                fetch_attempts=attempts,
                ingestion_item_id=ingestion_item_id,
                error=None,
                fetched_at=fetched_at,
                updated_at=func.now(),
            )
            .returning(CrawlItem)
        )
        return self.session.scalars(statement).one_or_none()

    def mark_item_failed(
        self,
        item_id: int,
        *,
        attempts: int,
        error: str,
    ) -> CrawlItem | None:
        statement = (
            update(CrawlItem)
            .where(
                CrawlItem.id == item_id,
                CrawlItem.fetch_status == PENDING_FETCH_STATUS,
            )
            .values(
                fetch_status=FAILED_FETCH_STATUS,
                fetch_attempts=attempts,
                ingestion_item_id=None,
                error=error,
                fetched_at=None,
                updated_at=func.now(),
            )
            .returning(CrawlItem)
        )
        return self.session.scalars(statement).one_or_none()

    def list_pending_item_ids(self, job_id: UUID) -> list[int]:
        statement = (
            select(CrawlItem.id)
            .where(
                CrawlItem.job_id == job_id,
                CrawlItem.fetch_status == FETCHED_FETCH_STATUS,
                CrawlItem.ingestion_item_id.is_not(None),
                IngestionItem.status == PENDING_ITEM_STATUS,
            )
            .join(
                IngestionItem,
                IngestionItem.id == CrawlItem.ingestion_item_id,
            )
            .order_by(CrawlItem.position.asc())
        )
        return list(self.session.scalars(statement).all())

    def counts(self, job_id: UUID) -> CrawlCounts:
        statement = (
            select(
                func.count(CrawlItem.id),
                func.count(CrawlItem.id).filter(
                    CrawlItem.fetch_status == FETCHED_FETCH_STATUS
                ),
                func.count(IngestionItem.id).filter(
                    IngestionItem.status == IMPORTED_ITEM_STATUS
                ),
                func.count(IngestionItem.id).filter(
                    IngestionItem.status == SKIPPED_ITEM_STATUS
                ),
                func.count(CrawlItem.id).filter(
                    CrawlItem.fetch_status == FAILED_FETCH_STATUS
                ),
                func.count(IngestionItem.id).filter(
                    IngestionItem.status == FAILED_ITEM_STATUS
                ),
            )
            .select_from(CrawlItem)
            .outerjoin(
                IngestionItem,
                IngestionItem.id == CrawlItem.ingestion_item_id,
            )
            .where(CrawlItem.job_id == job_id)
        )
        row = self.session.execute(statement).one()
        return CrawlCounts(*(int(value or 0) for value in row))

    def count_item_views(self, job_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(CrawlItem)
            .where(CrawlItem.job_id == job_id)
        )
        return int(self.session.scalar(statement) or 0)

    def list_item_views(
        self,
        job_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[CrawlItemView]:
        self._validate_pagination(limit=limit, offset=offset)
        statement = (
            select(
                CrawlItem.position,
                CrawlItem.source_item_id,
                CrawlItem.title,
                CrawlItem.canonical_url,
                CrawlItem.fetch_status,
                IngestionItem.status,
                IngestionItem.document_id,
                func.coalesce(CrawlItem.error, IngestionItem.error),
            )
            .select_from(CrawlItem)
            .outerjoin(
                IngestionItem,
                IngestionItem.id == CrawlItem.ingestion_item_id,
            )
            .where(CrawlItem.job_id == job_id)
            .order_by(CrawlItem.position.asc())
            .limit(limit)
            .offset(offset)
        )
        return [CrawlItemView(*row) for row in self.session.execute(statement).all()]

    def checkpoint_discovery(
        self,
        job_id: UUID,
        frontier_id: int,
        discovered_items: list[DiscoveredItem],
        *,
        continuation: dict[str, Any] | None,
    ) -> DiscoveryCheckpoint:
        run = self.get_run_for_update(job_id)
        if run is None:
            raise ValueError("crawl_run_not_found")
        frontier = self.get_frontier_for_update(frontier_id)
        if frontier is None or frontier.job_id != job_id:
            raise ValueError("crawl_frontier_not_found")
        if run.discovery_complete or frontier.status != PENDING_FRONTIER_STATUS:
            raise ValueError("crawl_state_conflict")

        existing_urls = set(
            self.session.scalars(
                select(CrawlItem.canonical_url).where(
                    CrawlItem.job_id == job_id
                )
            ).all()
        )
        next_position = self._next_item_position(job_id)
        limit_reached = len(existing_urls) >= run.max_articles

        for discovered_item in discovered_items:
            if discovered_item.canonical_url in existing_urls:
                continue
            if limit_reached:
                break
            self.add_item(
                job_id,
                position=next_position,
                discovered_item=discovered_item,
            )
            existing_urls.add(discovered_item.canonical_url)
            next_position += 1
            limit_reached = len(existing_urls) >= run.max_articles

        if continuation is None or limit_reached:
            frontier.continuation = None
            frontier.status = COMPLETED_FRONTIER_STATUS
        else:
            frontier.continuation = dict(continuation)
            frontier.status = PENDING_FRONTIER_STATUS
        frontier.error = None
        run.limit_reached = limit_reached
        run.discovery_complete = limit_reached or continuation is None
        self.session.flush()
        discovered_count = self.count_item_views(job_id)
        return DiscoveryCheckpoint(
            discovered_count=discovered_count,
            discovery_complete=run.discovery_complete,
            limit_reached=run.limit_reached,
        )

    @staticmethod
    def _validate_pagination(*, limit: int, offset: int) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        if offset < 0:
            raise ValueError("offset cannot be negative.")

    def _next_item_position(self, job_id: UUID) -> int:
        statement = select(
            func.coalesce(func.max(CrawlItem.position) + 1, 0)
        ).where(CrawlItem.job_id == job_id)
        return int(self.session.scalar(statement) or 0)

    @staticmethod
    def _run_snapshot(model: CrawlRun) -> CrawlRunSnapshot:
        return CrawlRunSnapshot(
            job_id=model.job_id,
            source_key=model.source_key,
            seed_url=model.seed_url,
            max_articles=model.max_articles,
            max_depth=model.max_depth,
            discovery_complete=model.discovery_complete,
            limit_reached=model.limit_reached,
        )

    @staticmethod
    def _frontier_snapshot(model: CrawlFrontier) -> FrontierSnapshot:
        return FrontierSnapshot(
            id=model.id,
            locator=model.locator,
            depth=model.depth,
            continuation=model.continuation,
        )
