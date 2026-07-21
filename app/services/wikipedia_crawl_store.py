from dataclasses import dataclass
from uuid import UUID

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.wikipedia_crawl import (
    COMPLETED_FRONTIER_STATUS,
    PENDING_FRONTIER_STATUS,
)
from app.repositories.ingestion_items import IngestionItemRepository
from app.repositories.wikipedia_crawls import WikipediaCrawlRepository
from app.services.wikipedia_types import (
    CrawlCounts,
    CrawlRunSnapshot,
    FrontierSnapshot,
    WikipediaCategoryBatch,
    wikipedia_article_url,
)


class WikipediaCrawlStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoveryCheckpoint:
    discovered_count: int
    discovery_complete: bool
    category_limit_reached: bool


class WikipediaCrawlStore:
    def __init__(
        self,
        session_factory=SessionLocal,
        repository_factory=WikipediaCrawlRepository,
        ingestion_repository_factory=IngestionItemRepository,
        max_categories: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository_factory = repository_factory
        self.ingestion_repository_factory = ingestion_repository_factory
        self.max_categories = (
            get_settings().wikipedia_max_categories
            if max_categories is None
            else max_categories
        )
        if self.max_categories < 1:
            raise ValueError("max_categories must be positive")

    def get_run(self, job_id: UUID) -> CrawlRunSnapshot:
        session = self.session_factory()
        try:
            run = self.repository_factory(session).get_run(job_id)
            if run is None:
                raise WikipediaCrawlStateError("crawl_run_not_found")
            return run
        finally:
            session.close()

    def get_counts(self, job_id: UUID) -> CrawlCounts:
        session = self.session_factory()
        try:
            repository = self.repository_factory(session)
            if repository.get_run(job_id) is None:
                raise WikipediaCrawlStateError("crawl_run_not_found")
            return repository.counts(job_id)
        finally:
            session.close()

    def get_next_frontier(self, job_id: UUID) -> FrontierSnapshot | None:
        session = self.session_factory()
        try:
            repository = self.repository_factory(session)
            if repository.get_run(job_id) is None:
                raise WikipediaCrawlStateError("crawl_run_not_found")
            return repository.get_next_pending_frontier(job_id)
        finally:
            session.close()

    def checkpoint_discovery(
        self,
        job_id: UUID,
        frontier_id: int,
        batch: WikipediaCategoryBatch,
    ) -> DiscoveryCheckpoint:
        session = self.session_factory()
        try:
            repository = self.repository_factory(session)
            run = repository.get_run_for_update(job_id)
            if run is None:
                raise WikipediaCrawlStateError("crawl_run_not_found")

            frontier = repository.get_frontier_for_update(frontier_id)
            if frontier is None or frontier.job_id != job_id:
                raise WikipediaCrawlStateError("crawl_frontier_not_found")
            if (
                run.discovery_complete
                or frontier.status != PENDING_FRONTIER_STATUS
            ):
                raise WikipediaCrawlStateError("crawl_state_conflict")

            existing_page_ids = repository.list_page_ids(job_id)
            existing_category_titles = repository.list_category_titles(job_id)
            next_position = repository.next_page_position(job_id)
            article_limit_hit = len(existing_page_ids) >= run.max_articles

            for page in batch.pages:
                if page.page_id in existing_page_ids:
                    continue
                if article_limit_hit:
                    break
                repository.add_page(
                    job_id,
                    position=next_position,
                    wikipedia_page_id=page.page_id,
                    title=page.title,
                    canonical_url=wikipedia_article_url(page.title),
                )
                existing_page_ids.add(page.page_id)
                next_position += 1
                article_limit_hit = (
                    len(existing_page_ids) >= run.max_articles
                )

            if not article_limit_hit and frontier.depth < run.max_depth:
                frontier_count = repository.count_frontier(job_id)
                for category in batch.subcategories:
                    if category.title in existing_category_titles:
                        continue
                    if frontier_count >= self.max_categories:
                        run.category_limit_reached = True
                        continue
                    repository.add_frontier(
                        job_id,
                        category_title=category.title,
                        depth=frontier.depth + 1,
                    )
                    existing_category_titles.add(category.title)
                    frontier_count += 1

            if batch.continuation is None:
                frontier.continuation = None
                frontier.status = COMPLETED_FRONTIER_STATUS
            else:
                frontier.continuation = dict(batch.continuation)
                frontier.status = PENDING_FRONTIER_STATUS
            frontier.error = None

            session.flush()
            discovered_count = repository.count_pages(job_id)
            run.discovery_complete = article_limit_hit or not (
                repository.has_pending_frontier(job_id)
            )
            session.commit()
            return DiscoveryCheckpoint(
                discovered_count=discovered_count,
                discovery_complete=run.discovery_complete,
                category_limit_reached=run.category_limit_reached,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def complete_empty_frontier(self, job_id: UUID) -> int:
        session = self.session_factory()
        try:
            repository = self.repository_factory(session)
            run = repository.get_run_for_update(job_id)
            if run is None:
                raise WikipediaCrawlStateError("crawl_run_not_found")
            if repository.has_pending_frontier(job_id):
                raise WikipediaCrawlStateError("crawl_state_conflict")
            run.discovery_complete = True
            session.flush()
            discovered_count = repository.count_pages(job_id)
            session.commit()
            return discovered_count
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
