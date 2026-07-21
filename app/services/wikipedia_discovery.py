import logging
from uuid import UUID

from app.services.wikipedia_client import WikipediaClient
from app.services.wikipedia_crawl_store import WikipediaCrawlStore

logger = logging.getLogger(__name__)


class WikipediaDiscoveryRunner:
    def __init__(
        self,
        store: WikipediaCrawlStore,
        client: WikipediaClient,
    ) -> None:
        self.store = store
        self.client = client

    async def run(self, job_id: UUID) -> int:
        run = self.store.get_run(job_id)
        counts = self.store.get_counts(job_id)
        self._log(
            "wikipedia_discovery_started",
            job_id=job_id,
            category=run.root_category,
            depth=0,
            outcome="started",
            discovered_count=counts.discovered,
        )

        while True:
            if run.discovery_complete:
                self._log(
                    "wikipedia_discovery_completed",
                    job_id=job_id,
                    category=run.root_category,
                    depth=0,
                    outcome="already_complete",
                    discovered_count=counts.discovered,
                )
                return counts.discovered

            frontier = self.store.get_next_frontier(job_id)
            if frontier is None:
                discovered_count = self.store.complete_empty_frontier(job_id)
                self._log(
                    "wikipedia_discovery_completed",
                    job_id=job_id,
                    category=run.root_category,
                    depth=0,
                    outcome="completed",
                    discovered_count=discovered_count,
                )
                return discovered_count

            batch = await self.client.discover_category(
                frontier.category_title,
                frontier.continuation,
            )
            checkpoint = self.store.checkpoint_discovery(
                job_id,
                frontier.id,
                batch,
            )
            self._log(
                "wikipedia_discovery_checkpointed",
                job_id=job_id,
                category=frontier.category_title,
                depth=frontier.depth,
                outcome="checkpointed",
                discovered_count=checkpoint.discovered_count,
            )
            if checkpoint.discovery_complete:
                self._log(
                    "wikipedia_discovery_completed",
                    job_id=job_id,
                    category=frontier.category_title,
                    depth=frontier.depth,
                    outcome="completed",
                    discovered_count=checkpoint.discovered_count,
                )
                return checkpoint.discovered_count

            run = self.store.get_run(job_id)
            counts = self.store.get_counts(job_id)

    @staticmethod
    def _log(
        event: str,
        *,
        job_id: UUID,
        category: str,
        depth: int,
        outcome: str,
        discovered_count: int,
    ) -> None:
        logger.info(
            event,
            extra={
                "job_id": str(job_id),
                "phase": "discovery",
                "category": category,
                "depth": depth,
                "outcome": outcome,
                "discovered_count": discovered_count,
            },
        )
