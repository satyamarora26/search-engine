import asyncio
from collections.abc import Callable
import logging
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.models.job import (
    FAILURE_STATUS,
    MEDIUM_CRAWL_JOB,
    PENDING_STATUS,
    STARTED_STATUS,
    SUCCESS_STATUS,
)
from app.services.crawl_adapters import CrawlAdapter, get_adapter
from app.services.crawl_store import CrawlStateError, CrawlStore
from app.services.crawl_types import (
    CrawlCounts,
    CrawlLimits,
    CrawlerError,
    NormalizedSeed,
)
from app.services.document_ingestion import IngestionItemProcessor
from app.services.job_tracker import JobTracker, JobTransitionError
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)
from app.workers.search_tasks import rebuild_search_index_snapshot

logger = logging.getLogger(__name__)


class CrawlCompletionError(Exception):
    pass


class CrawlRunner:
    def __init__(
        self,
        tracker: JobTracker | None = None,
        store: CrawlStore | None = None,
        processor: IngestionItemProcessor | None = None,
        adapter_resolver: Callable[[str], CrawlAdapter] = get_adapter,
        rebuild: Callable[[str], dict[str, Any]] = rebuild_search_index_snapshot,
        snapshot_store: RedisSearchIndexStore | None = None,
    ) -> None:
        self.tracker = tracker or JobTracker()
        self.store = store or CrawlStore()
        self.processor = processor or IngestionItemProcessor()
        self.adapter_resolver = adapter_resolver
        self.rebuild = rebuild
        self.snapshot_store = snapshot_store or create_redis_search_index_store()

    def run(self, job_id: UUID) -> dict[str, Any]:
        return asyncio.run(self._run(job_id))

    async def _run(self, job_id: UUID) -> dict[str, Any]:
        job = self.tracker.get_job(job_id)
        if job is None or job.job_type != MEDIUM_CRAWL_JOB:
            raise JobTransitionError("Medium crawl job is missing or invalid.")
        if job.status == SUCCESS_STATUS:
            return dict(job.result or {})
        if job.status == FAILURE_STATUS:
            raise JobTransitionError("Medium crawl job has already failed.")
        if job.status not in (PENDING_STATUS, STARTED_STATUS):
            raise JobTransitionError("Medium crawl job has invalid status.")
        if job.status == PENDING_STATUS:
            if not self.tracker.claim(
                job_id,
                progress_current=0,
                progress_total=None,
                progress_message="Discovering Medium articles",
            ):
                raise JobTransitionError("Medium crawl job could not be claimed.")

        run = self._get_run(job_id)
        adapter = self.adapter_resolver(run.source_key)
        seed = adapter.validate_seed(run.seed_url)
        limits = CrawlLimits(
            max_articles=run.max_articles,
            max_depth=run.max_depth,
            max_response_bytes=get_settings().medium_max_response_bytes,
        )

        async with adapter:
            if not run.discovery_complete:
                self._log(job_id, "discovery", "started")
                async for batch in adapter.discover(seed, limits):
                    self.store.checkpoint_discovery(job_id, batch)
                    counts = self._get_counts(job_id)
                    self.tracker.update_progress(
                        job_id,
                        progress_current=counts.terminal,
                        progress_total=None,
                        progress_message="Discovering Medium articles",
                    )
                run = self._get_run(job_id)
                self._log(job_id, "discovery", "completed")

            counts = self._get_counts(job_id)
            if counts.discovered == 0:
                raise CrawlCompletionError("medium_crawl_no_articles")

            progress_total = counts.discovered + 1
            self.tracker.update_progress(
                job_id,
                progress_current=counts.terminal,
                progress_total=progress_total,
                progress_message="Fetching Medium articles",
            )
            self._log(job_id, "fetch", "started")
            for item in self.store.list_pending_items(job_id):
                try:
                    raw_page = await adapter.fetch(item.discovered_item)
                    document = adapter.parse(raw_page)
                    self.store.stage_fetched_document(
                        item.id,
                        document,
                        attempts=raw_page.attempts,
                    )
                except CrawlerError as error:
                    self.store.fail_item(
                        item.id,
                        attempts=max(1, error.attempts),
                        error=error.code,
                    )
                except Exception:
                    logger.exception("Medium crawl item %s failed.", item.id)
                    self.store.fail_item(
                        item.id,
                        attempts=1,
                        error="medium_item_failed",
                    )
                counts = self._get_counts(job_id)
                self.tracker.update_progress(
                    job_id,
                    progress_current=counts.terminal,
                    progress_total=progress_total,
                    progress_message=(
                        f"Fetched article {counts.terminal} "
                        f"of {counts.discovered}"
                    ),
                )
            counts = self._get_counts(job_id)
            if counts.fetched == 0:
                raise CrawlCompletionError("medium_crawl_no_fetched_articles")
            self._log(job_id, "fetch", "completed")

        self.tracker.update_progress(
            job_id,
            progress_current=counts.terminal,
            progress_total=progress_total,
            progress_message="Ingesting Medium articles",
        )
        for ingestion_item_id in self.store.list_pending_ingestion_ids(job_id):
            self.processor.process(ingestion_item_id)
            counts = self._get_counts(job_id)
            self.tracker.update_progress(
                job_id,
                progress_current=counts.terminal,
                progress_total=progress_total,
                progress_message=(
                    f"Processed article {counts.terminal} "
                    f"of {counts.discovered}"
                ),
            )

        counts = self._get_counts(job_id)
        if counts.imported + counts.skipped == 0:
            raise CrawlCompletionError("medium_crawl_no_usable_documents")

        if counts.imported:
            self.tracker.update_progress(
                job_id,
                progress_current=counts.discovered,
                progress_total=progress_total,
                progress_message="Rebuilding search index",
            )
            index_version = self.rebuild(f"redis-{job_id}")["index_version"]
            index_rebuilt = True
        else:
            self.tracker.update_progress(
                job_id,
                progress_current=counts.discovered,
                progress_total=progress_total,
                progress_message="No index changes required",
            )
            index_version = self.snapshot_store.get_active_version()
            index_rebuilt = False

        result = self._build_result(run, counts, index_rebuilt, index_version)
        self.tracker.mark_success(
            job_id,
            result=result,
            progress_total=progress_total,
            progress_message="Medium crawl completed",
        )
        return result

    def _get_run(self, job_id: UUID):
        try:
            return self.store.get_run(job_id)
        except CrawlStateError as error:
            raise JobTransitionError("Medium crawl state is missing or invalid.") from error

    def _get_counts(self, job_id: UUID) -> CrawlCounts:
        try:
            return self.store.get_counts(job_id)
        except CrawlStateError as error:
            raise JobTransitionError("Medium crawl state is missing or invalid.") from error

    @staticmethod
    def _build_result(run, counts, index_rebuilt, index_version):
        return {
            "source": run.source_key,
            "seed_url": run.seed_url,
            "max_articles": run.max_articles,
            "max_depth": run.max_depth,
            "discovered_count": counts.discovered,
            "fetched_count": counts.fetched,
            "imported_count": counts.imported,
            "duplicate_skipped_count": counts.skipped,
            "fetch_failed_count": counts.fetch_failed,
            "ingestion_failed_count": counts.ingestion_failed,
            "failed_count": counts.failed,
            "index_rebuilt": index_rebuilt,
            "index_version": index_version,
        }

    @staticmethod
    def _log(job_id: UUID, phase: str, outcome: str) -> None:
        logger.info(
            "medium_crawl_phase",
            extra={"job_id": str(job_id), "phase": phase, "outcome": outcome},
        )
