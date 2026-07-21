from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.models.ingestion_item import (
    FAILED_ITEM_STATUS,
    IMPORTED_ITEM_STATUS,
    PENDING_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    IngestionItem,
)
from app.models.wikipedia_crawl import (
    COMPLETED_FRONTIER_STATUS,
    FAILED_FETCH_STATUS,
    FAILED_FRONTIER_STATUS,
    FETCHED_FETCH_STATUS,
    PENDING_FETCH_STATUS,
    PENDING_FRONTIER_STATUS,
    WikipediaCrawlFrontier,
    WikipediaCrawlPage,
    WikipediaCrawlRun,
)
from app.services.wikipedia_types import (
    CrawlCounts,
    CrawlItemView,
    CrawlPageSnapshot,
    CrawlRunSnapshot,
    FrontierSnapshot,
)


class WikipediaCrawlRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(
        self,
        job_id: UUID,
        *,
        root_category: str,
        max_articles: int,
        max_depth: int,
    ) -> WikipediaCrawlRun:
        run = WikipediaCrawlRun(
            job_id=job_id,
            root_category=root_category,
            max_articles=max_articles,
            max_depth=max_depth,
            discovery_complete=False,
            category_limit_reached=False,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def add_frontier(
        self,
        job_id: UUID,
        *,
        category_title: str,
        depth: int,
    ) -> WikipediaCrawlFrontier:
        frontier = WikipediaCrawlFrontier(
            job_id=job_id,
            category_title=category_title,
            depth=depth,
            continuation=None,
            status=PENDING_FRONTIER_STATUS,
            error=None,
        )
        self.session.add(frontier)
        self.session.flush()
        return frontier

    def get_run(self, job_id: UUID) -> CrawlRunSnapshot | None:
        model = self.session.scalars(
            select(WikipediaCrawlRun).where(
                WikipediaCrawlRun.job_id == job_id
            )
        ).one_or_none()
        return self._run_snapshot(model) if model is not None else None

    def get_run_for_update(
        self,
        job_id: UUID,
    ) -> WikipediaCrawlRun | None:
        statement = (
            select(WikipediaCrawlRun)
            .where(WikipediaCrawlRun.job_id == job_id)
            .with_for_update()
        )
        return self.session.scalars(statement).one_or_none()

    def get_frontier_for_update(
        self,
        frontier_id: int,
    ) -> WikipediaCrawlFrontier | None:
        statement = (
            select(WikipediaCrawlFrontier)
            .where(WikipediaCrawlFrontier.id == frontier_id)
            .with_for_update()
        )
        return self.session.scalars(statement).one_or_none()

    def get_next_pending_frontier(
        self,
        job_id: UUID,
    ) -> FrontierSnapshot | None:
        statement = (
            select(WikipediaCrawlFrontier)
            .where(
                WikipediaCrawlFrontier.job_id == job_id,
                WikipediaCrawlFrontier.status == PENDING_FRONTIER_STATUS,
            )
            .order_by(
                WikipediaCrawlFrontier.depth.asc(),
                WikipediaCrawlFrontier.id.asc(),
            )
            .limit(1)
        )
        model = self.session.scalars(statement).one_or_none()
        return self._frontier_snapshot(model) if model is not None else None

    def list_page_ids(self, job_id: UUID) -> set[int]:
        statement = select(WikipediaCrawlPage.wikipedia_page_id).where(
            WikipediaCrawlPage.job_id == job_id
        )
        return set(self.session.scalars(statement).all())

    def list_category_titles(self, job_id: UUID) -> set[str]:
        statement = select(WikipediaCrawlFrontier.category_title).where(
            WikipediaCrawlFrontier.job_id == job_id
        )
        return set(self.session.scalars(statement).all())

    def next_page_position(self, job_id: UUID) -> int:
        statement = select(
            func.coalesce(func.max(WikipediaCrawlPage.position) + 1, 0)
        ).where(WikipediaCrawlPage.job_id == job_id)
        return int(self.session.scalar(statement) or 0)

    def count_frontier(self, job_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(WikipediaCrawlFrontier)
            .where(WikipediaCrawlFrontier.job_id == job_id)
        )
        return int(self.session.scalar(statement) or 0)

    def count_pages(self, job_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(WikipediaCrawlPage)
            .where(WikipediaCrawlPage.job_id == job_id)
        )
        return int(self.session.scalar(statement) or 0)

    def has_pending_frontier(self, job_id: UUID) -> bool:
        statement = select(
            exists().where(
                WikipediaCrawlFrontier.job_id == job_id,
                WikipediaCrawlFrontier.status == PENDING_FRONTIER_STATUS,
            )
        )
        return bool(self.session.scalar(statement))

    def add_page(
        self,
        job_id: UUID,
        *,
        position: int,
        wikipedia_page_id: int,
        title: str,
        canonical_url: str,
    ) -> WikipediaCrawlPage:
        page = WikipediaCrawlPage(
            job_id=job_id,
            position=position,
            wikipedia_page_id=wikipedia_page_id,
            title=title,
            canonical_url=canonical_url,
            fetch_status=PENDING_FETCH_STATUS,
            fetch_attempts=0,
        )
        self.session.add(page)
        self.session.flush()
        return page

    def list_pending_pages(
        self,
        job_id: UUID,
        *,
        limit: int,
    ) -> list[CrawlPageSnapshot]:
        self._validate_pagination(limit=limit, offset=0)
        statement = (
            select(WikipediaCrawlPage)
            .where(
                WikipediaCrawlPage.job_id == job_id,
                WikipediaCrawlPage.fetch_status == PENDING_FETCH_STATUS,
            )
            .order_by(WikipediaCrawlPage.position.asc())
            .limit(limit)
        )
        return [
            self._page_snapshot(model)
            for model in self.session.scalars(statement).all()
        ]

    def get_page_for_update(
        self,
        page_id: int,
    ) -> WikipediaCrawlPage | None:
        statement = (
            select(WikipediaCrawlPage)
            .where(WikipediaCrawlPage.id == page_id)
            .with_for_update()
        )
        return self.session.scalars(statement).one_or_none()

    def mark_page_fetched(
        self,
        page_id: int,
        *,
        attempts: int,
        ingestion_item_id: int,
        fetched_at: datetime,
    ) -> WikipediaCrawlPage | None:
        statement = (
            update(WikipediaCrawlPage)
            .where(
                WikipediaCrawlPage.id == page_id,
                WikipediaCrawlPage.fetch_status == PENDING_FETCH_STATUS,
            )
            .values(
                fetch_status=FETCHED_FETCH_STATUS,
                fetch_attempts=attempts,
                ingestion_item_id=ingestion_item_id,
                error=None,
                fetched_at=fetched_at,
                updated_at=func.now(),
            )
            .returning(WikipediaCrawlPage)
        )
        return self.session.scalars(statement).one_or_none()

    def mark_page_failed(
        self,
        page_id: int,
        *,
        attempts: int,
        error: str,
    ) -> WikipediaCrawlPage | None:
        statement = (
            update(WikipediaCrawlPage)
            .where(
                WikipediaCrawlPage.id == page_id,
                WikipediaCrawlPage.fetch_status == PENDING_FETCH_STATUS,
            )
            .values(
                fetch_status=FAILED_FETCH_STATUS,
                fetch_attempts=attempts,
                ingestion_item_id=None,
                error=error,
                fetched_at=None,
                updated_at=func.now(),
            )
            .returning(WikipediaCrawlPage)
        )
        return self.session.scalars(statement).one_or_none()

    def list_pending_ingestion_ids(self, job_id: UUID) -> list[int]:
        statement = (
            select(IngestionItem.id)
            .join(
                WikipediaCrawlPage,
                WikipediaCrawlPage.ingestion_item_id == IngestionItem.id,
            )
            .where(
                WikipediaCrawlPage.job_id == job_id,
                IngestionItem.status == PENDING_ITEM_STATUS,
            )
            .order_by(WikipediaCrawlPage.position.asc())
        )
        return list(self.session.scalars(statement).all())

    def counts(self, job_id: UUID) -> CrawlCounts:
        categories_visited = (
            select(func.count(WikipediaCrawlFrontier.id))
            .where(
                WikipediaCrawlFrontier.job_id == job_id,
                or_(
                    WikipediaCrawlFrontier.status.in_(
                        (
                            COMPLETED_FRONTIER_STATUS,
                            FAILED_FRONTIER_STATUS,
                        )
                    ),
                    WikipediaCrawlFrontier.continuation.is_not(None),
                ),
            )
            .scalar_subquery()
        )
        statement = (
            select(
                categories_visited,
                func.count(WikipediaCrawlPage.id),
                func.count(WikipediaCrawlPage.id).filter(
                    WikipediaCrawlPage.fetch_status == FETCHED_FETCH_STATUS
                ),
                func.count(IngestionItem.id).filter(
                    IngestionItem.status == IMPORTED_ITEM_STATUS
                ),
                func.count(IngestionItem.id).filter(
                    IngestionItem.status == SKIPPED_ITEM_STATUS
                ),
                func.count(WikipediaCrawlPage.id).filter(
                    WikipediaCrawlPage.fetch_status == FAILED_FETCH_STATUS
                ),
                func.count(IngestionItem.id).filter(
                    IngestionItem.status == FAILED_ITEM_STATUS
                ),
            )
            .select_from(WikipediaCrawlPage)
            .outerjoin(
                IngestionItem,
                IngestionItem.id == WikipediaCrawlPage.ingestion_item_id,
            )
            .where(WikipediaCrawlPage.job_id == job_id)
        )
        row = self.session.execute(statement).one()
        return CrawlCounts(*(int(value or 0) for value in row))

    def count_item_views(self, job_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(WikipediaCrawlPage)
            .where(WikipediaCrawlPage.job_id == job_id)
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
                WikipediaCrawlPage.position,
                WikipediaCrawlPage.wikipedia_page_id,
                WikipediaCrawlPage.title,
                WikipediaCrawlPage.canonical_url,
                WikipediaCrawlPage.fetch_status,
                IngestionItem.status,
                IngestionItem.document_id,
                func.coalesce(
                    WikipediaCrawlPage.error,
                    IngestionItem.error,
                ),
            )
            .select_from(WikipediaCrawlPage)
            .outerjoin(
                IngestionItem,
                IngestionItem.id == WikipediaCrawlPage.ingestion_item_id,
            )
            .where(WikipediaCrawlPage.job_id == job_id)
            .order_by(WikipediaCrawlPage.position.asc())
            .limit(limit)
            .offset(offset)
        )
        return [CrawlItemView(*row) for row in self.session.execute(statement).all()]

    @staticmethod
    def _validate_pagination(*, limit: int, offset: int) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        if offset < 0:
            raise ValueError("offset cannot be negative.")

    @staticmethod
    def _run_snapshot(model: WikipediaCrawlRun) -> CrawlRunSnapshot:
        return CrawlRunSnapshot(
            job_id=model.job_id,
            root_category=model.root_category,
            max_articles=model.max_articles,
            max_depth=model.max_depth,
            discovery_complete=model.discovery_complete,
            category_limit_reached=model.category_limit_reached,
        )

    @staticmethod
    def _frontier_snapshot(
        model: WikipediaCrawlFrontier,
    ) -> FrontierSnapshot:
        return FrontierSnapshot(
            id=model.id,
            category_title=model.category_title,
            depth=model.depth,
            continuation=model.continuation,
        )

    @staticmethod
    def _page_snapshot(model: WikipediaCrawlPage) -> CrawlPageSnapshot:
        return CrawlPageSnapshot(
            id=model.id,
            position=model.position,
            wikipedia_page_id=model.wikipedia_page_id,
            title=model.title,
            canonical_url=model.canonical_url,
        )
