from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.crawl import PENDING_FETCH_STATUS
from app.repositories.crawls import CrawlRepository
from app.repositories.ingestion_items import IngestionItemRepository
from app.services.crawl_types import (
    CrawlCounts,
    CrawlItemSnapshot,
    CrawlRunSnapshot,
    DiscoveryBatch,
    DiscoveryCheckpoint,
    NormalizedDocument,
)

T = TypeVar("T")


class CrawlStateError(RuntimeError):
    pass


class CrawlStore:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        repository_factory: Callable[[Session], CrawlRepository] = CrawlRepository,
        ingestion_repository_factory: Callable[
            [Session], IngestionItemRepository
        ] = IngestionItemRepository,
    ) -> None:
        self.session_factory = session_factory
        self.repository_factory = repository_factory
        self.ingestion_repository_factory = ingestion_repository_factory

    def get_run(self, job_id: UUID) -> CrawlRunSnapshot:
        return self._read_required(
            lambda repository: repository.get_run(job_id),
            "crawl_run_not_found",
        )

    def get_counts(self, job_id: UUID) -> CrawlCounts:
        def read(repository: CrawlRepository) -> CrawlCounts:
            if repository.get_run(job_id) is None:
                raise CrawlStateError("crawl_run_not_found")
            return repository.counts(job_id)

        return self._read(read)

    def checkpoint_discovery(
        self,
        job_id: UUID,
        batch: DiscoveryBatch,
    ) -> DiscoveryCheckpoint:
        session = self.session_factory()
        try:
            repository = self.repository_factory(session)
            frontier = repository.get_frontier_by_locator(
                job_id,
                batch.frontier_locator,
            )
            if frontier is None:
                raise CrawlStateError("crawl_frontier_not_found")
            checkpoint = repository.checkpoint_discovery(
                job_id,
                frontier.id,
                list(batch.items),
                continuation=batch.continuation,
                discovery_complete=batch.complete,
            )
            session.commit()
            return checkpoint
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_pending_items(
        self,
        job_id: UUID,
        *,
        limit: int = 100,
    ) -> list[CrawlItemSnapshot]:
        return self._read(
            lambda repository: repository.list_pending_items(
                job_id,
                limit=limit,
            )
        )

    def stage_fetched_document(
        self,
        crawl_item_id: int,
        document: NormalizedDocument,
        *,
        attempts: int,
    ) -> None:
        session = self.session_factory()
        try:
            repository = self.repository_factory(session)
            item = repository.get_item_for_update(crawl_item_id)
            if item is None:
                raise CrawlStateError("crawl_item_not_found")
            if item.fetch_status != PENDING_FETCH_STATUS:
                session.commit()
                return
            ingestion_item = self.ingestion_repository_factory(session).stage_at_position(
                item.job_id,
                item.position,
                {
                    "title": document.title,
                    "content": document.content,
                    "url": document.canonical_url,
                },
            )
            updated = repository.mark_item_fetched(
                crawl_item_id,
                attempts=attempts,
                ingestion_item_id=ingestion_item.id,
                fetched_at=datetime.now(timezone.utc),
                title=document.title,
            )
            if updated is None:
                raise CrawlStateError("crawl_state_conflict")
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def fail_item(
        self,
        crawl_item_id: int,
        *,
        attempts: int,
        error: str,
    ) -> None:
        session = self.session_factory()
        try:
            repository = self.repository_factory(session)
            item = repository.get_item_for_update(crawl_item_id)
            if item is None:
                raise CrawlStateError("crawl_item_not_found")
            if item.fetch_status != PENDING_FETCH_STATUS:
                session.commit()
                return
            updated = repository.mark_item_failed(
                crawl_item_id,
                attempts=attempts,
                error=_safe_error(error),
            )
            if updated is None:
                raise CrawlStateError("crawl_state_conflict")
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_pending_ingestion_ids(self, job_id: UUID) -> list[int]:
        return self._read(
            lambda repository: repository.list_pending_ingestion_ids(job_id)
        )

    def _read_required(
        self,
        operation: Callable[[CrawlRepository], T | None],
        error: str,
    ) -> T:
        result = self._read(operation)
        if result is None:
            raise CrawlStateError(error)
        return result

    def _read(self, operation: Callable[[CrawlRepository], T]) -> T:
        session = self.session_factory()
        try:
            return operation(self.repository_factory(session))
        finally:
            session.close()


def _safe_error(error: str) -> str:
    return " ".join(str(error).split())[:300]
