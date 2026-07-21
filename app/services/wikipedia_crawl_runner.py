import asyncio
from collections.abc import Callable
import logging
from typing import Any
from uuid import UUID

from app.models.job import (
    FAILURE_STATUS,
    PENDING_STATUS,
    STARTED_STATUS,
    SUCCESS_STATUS,
    WIKIPEDIA_CRAWL_JOB,
)
from app.services.document_ingestion import IngestionItemProcessor
from app.services.job_tracker import JobTracker, JobTransitionError
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)
from app.services.wikipedia_client import (
    WikipediaClient,
    create_wikipedia_client,
)
from app.services.wikipedia_crawl_store import (
    WikipediaCrawlStateError,
    WikipediaCrawlStore,
)
from app.services.wikipedia_discovery import WikipediaDiscoveryRunner
from app.services.wikipedia_fetching import WikipediaFetchRunner
from app.services.wikipedia_types import CrawlCounts, CrawlRunSnapshot
from app.workers.search_tasks import rebuild_search_index_snapshot

logger = logging.getLogger(__name__)


class WikipediaCrawlCompletionError(Exception):
    pass


class WikipediaCrawlRunner:
    def __init__(
        self,
        tracker: JobTracker | None = None,
        store: WikipediaCrawlStore | None = None,
        processor: IngestionItemProcessor | None = None,
        client_factory: Callable[[], WikipediaClient] = (
            create_wikipedia_client
        ),
        discovery_factory: Callable[
            [WikipediaCrawlStore, WikipediaClient],
            WikipediaDiscoveryRunner,
        ] = WikipediaDiscoveryRunner,
        fetching_factory: Callable[
            [WikipediaCrawlStore, WikipediaClient],
            WikipediaFetchRunner,
        ] = WikipediaFetchRunner,
        rebuild: Callable[
            [str], dict[str, Any]
        ] = rebuild_search_index_snapshot,
        snapshot_store: RedisSearchIndexStore | None = None,
    ) -> None:
        self.tracker = tracker or JobTracker()
        self.store = store or WikipediaCrawlStore()
        self.processor = processor or IngestionItemProcessor()
        self.client_factory = client_factory
        self.discovery_factory = discovery_factory
        self.fetching_factory = fetching_factory
        self.rebuild = rebuild
        self.snapshot_store = (
            snapshot_store or create_redis_search_index_store()
        )

    def run(self, job_id: UUID) -> dict[str, Any]:
        return asyncio.run(self._run(job_id))

    async def _run(self, job_id: UUID) -> dict[str, Any]:
        job = self.tracker.get_job(job_id)
        if job is None or job.job_type != WIKIPEDIA_CRAWL_JOB:
            raise JobTransitionError(
                "Wikipedia crawl job is missing or invalid."
            )
        if job.status == SUCCESS_STATUS:
            return dict(job.result or {})
        if job.status == FAILURE_STATUS:
            raise JobTransitionError(
                "Wikipedia crawl job has already failed."
            )
        if job.status not in (PENDING_STATUS, STARTED_STATUS):
            raise JobTransitionError(
                "Wikipedia crawl job has invalid status."
            )
        if job.status == PENDING_STATUS:
            claimed = self.tracker.claim(
                job_id,
                progress_current=0,
                progress_total=None,
                progress_message="Discovering Wikipedia articles",
            )
            if not claimed:
                raise JobTransitionError(
                    "Wikipedia crawl job could not be claimed."
                )

        run = self._get_run(job_id)
        counts = self._get_counts(job_id)
        async with self.client_factory() as client:
            discovery = self.discovery_factory(self.store, client)
            fetching = self.fetching_factory(self.store, client)

            if run.discovery_complete:
                self._log_phase(
                    job_id=job_id,
                    phase="discovery",
                    outcome="skipped_complete",
                    counts=counts,
                )
            else:
                self._log_phase(
                    job_id=job_id,
                    phase="discovery",
                    outcome="started",
                    counts=counts,
                )
                await discovery.run(job_id)
                run = self._get_run(job_id)
                counts = self._get_counts(job_id)
                self._log_phase(
                    job_id=job_id,
                    phase="discovery",
                    outcome="completed",
                    counts=counts,
                )

            if counts.discovered == 0:
                raise WikipediaCrawlCompletionError(
                    "wikipedia_crawl_no_articles"
                )

            progress_total = counts.discovered + 1
            self.tracker.update_progress(
                job_id,
                progress_current=counts.terminal,
                progress_total=progress_total,
                progress_message="Fetching Wikipedia articles",
            )
            self._log_phase(
                job_id=job_id,
                phase="fetch",
                outcome="started",
                counts=counts,
            )
            await fetching.run(
                job_id,
                progress_callback=lambda current: (
                    self.tracker.update_progress(
                        job_id,
                        progress_current=current,
                        progress_total=progress_total,
                        progress_message="Fetching Wikipedia articles",
                    )
                ),
            )
            counts = self._get_counts(job_id)
            self._validate_fetch_counts(counts)
            self._log_phase(
                job_id=job_id,
                phase="fetch",
                outcome="completed",
                counts=counts,
            )

        if counts.fetched == 0:
            raise WikipediaCrawlCompletionError(
                "wikipedia_crawl_no_fetched_articles"
            )

        self.tracker.update_progress(
            job_id,
            progress_current=counts.terminal,
            progress_total=progress_total,
            progress_message="Ingesting Wikipedia articles",
        )
        self._log_phase(
            job_id=job_id,
            phase="ingestion",
            outcome="started",
            counts=counts,
        )
        for item_id in self._list_pending_ingestion_ids(job_id):
            self.processor.process(item_id)
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
        self._validate_ingestion_counts(counts)
        self._log_phase(
            job_id=job_id,
            phase="ingestion",
            outcome="completed",
            counts=counts,
        )
        if counts.imported + counts.skipped == 0:
            raise WikipediaCrawlCompletionError(
                "wikipedia_crawl_no_usable_documents"
            )

        if counts.imported:
            publication_message = "Rebuilding search index"
            publication_outcome = "rebuilding"
        else:
            publication_message = "No index changes required"
            publication_outcome = "no_changes"
        self.tracker.update_progress(
            job_id,
            progress_current=counts.discovered,
            progress_total=progress_total,
            progress_message=publication_message,
        )
        self._log_phase(
            job_id=job_id,
            phase="publication",
            outcome=publication_outcome,
            counts=counts,
        )

        if counts.imported:
            rebuild_status = self.rebuild(f"redis-{job_id}")
            index_version = rebuild_status["index_version"]
            index_rebuilt = True
        else:
            index_version = self.snapshot_store.get_active_version()
            index_rebuilt = False

        run = self._get_run(job_id)
        counts = self._get_counts(job_id)
        self._validate_fetch_counts(counts)
        self._validate_ingestion_counts(counts)
        result = self._build_result(
            run,
            counts,
            index_rebuilt=index_rebuilt,
            index_version=index_version,
        )
        self._log_phase(
            job_id=job_id,
            phase="publication",
            outcome="completed",
            counts=counts,
        )
        self.tracker.mark_success(
            job_id,
            result=result,
            progress_total=counts.discovered + 1,
            progress_message="Wikipedia crawl completed",
        )
        self._log_event(
            "wikipedia_crawl_completed",
            job_id=job_id,
            phase="completion",
            outcome="success",
            counts=counts,
        )
        return result

    def _get_run(self, job_id: UUID) -> CrawlRunSnapshot:
        try:
            return self.store.get_run(job_id)
        except WikipediaCrawlStateError as error:
            raise JobTransitionError(
                "Wikipedia crawl state is missing or invalid."
            ) from error

    def _get_counts(self, job_id: UUID) -> CrawlCounts:
        try:
            return self.store.get_counts(job_id)
        except WikipediaCrawlStateError as error:
            raise JobTransitionError(
                "Wikipedia crawl state is missing or invalid."
            ) from error

    def _list_pending_ingestion_ids(self, job_id: UUID) -> list[int]:
        try:
            return self.store.list_pending_ingestion_ids(job_id)
        except WikipediaCrawlStateError as error:
            raise JobTransitionError(
                "Wikipedia crawl state is missing or invalid."
            ) from error

    @staticmethod
    def _validate_fetch_counts(counts: CrawlCounts) -> None:
        if counts.fetched + counts.fetch_failed != counts.discovered:
            raise JobTransitionError(
                "Wikipedia crawl fetch counts are inconsistent."
            )

    @staticmethod
    def _validate_ingestion_counts(counts: CrawlCounts) -> None:
        if (
            counts.imported + counts.skipped + counts.ingestion_failed
            != counts.fetched
        ):
            raise JobTransitionError(
                "Wikipedia crawl ingestion counts are inconsistent."
            )

    @staticmethod
    def _build_result(
        run: CrawlRunSnapshot,
        counts: CrawlCounts,
        *,
        index_rebuilt: bool,
        index_version: str | None,
    ) -> dict[str, Any]:
        return {
            "root_category": run.root_category,
            "max_articles": run.max_articles,
            "max_depth": run.max_depth,
            "categories_visited": counts.categories_visited,
            "category_limit_reached": run.category_limit_reached,
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

    @classmethod
    def _log_phase(
        cls,
        *,
        job_id: UUID,
        phase: str,
        outcome: str,
        counts: CrawlCounts,
    ) -> None:
        cls._log_event(
            "wikipedia_crawl_phase",
            job_id=job_id,
            phase=phase,
            outcome=outcome,
            counts=counts,
        )

    @staticmethod
    def _log_event(
        event: str,
        *,
        job_id: UUID,
        phase: str,
        outcome: str,
        counts: CrawlCounts,
    ) -> None:
        logger.info(
            event,
            extra={
                "job_id": str(job_id),
                "phase": phase,
                "outcome": outcome,
                "discovered_count": counts.discovered,
                "fetched_count": counts.fetched,
                "terminal_count": counts.terminal,
            },
        )
