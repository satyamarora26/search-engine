import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
from uuid import UUID

from app.services.wikipedia_client import WikipediaRequestError
from app.services.wikipedia_extraction import (
    WikipediaExtractionError,
    extract_wikipedia_text,
)
from app.services.wikipedia_types import CrawlPageSnapshot

logger = logging.getLogger(__name__)

_FETCH_BATCH_SIZE = 20


@dataclass(frozen=True)
class _FetchResult:
    page: CrawlPageSnapshot
    attempts: int
    payload: dict[str, str] | None
    error_code: str | None


class WikipediaFetchRunner:
    def __init__(
        self,
        store,
        client,
        *,
        extractor: Callable[[str], str] = extract_wikipedia_text,
    ) -> None:
        self.store = store
        self.client = client
        self.extractor = extractor

    async def run(
        self,
        job_id: UUID,
        *,
        progress_callback: Callable[[int], None],
    ) -> None:
        while True:
            pending_pages = self.store.list_pending_pages(
                job_id,
                limit=_FETCH_BATCH_SIZE,
            )[:_FETCH_BATCH_SIZE]
            if not pending_pages:
                return

            results = await asyncio.gather(
                *(self._fetch(page) for page in pending_pages)
            )
            for result in results:
                if result.error_code is None:
                    if result.payload is None:
                        raise AssertionError("successful fetch has no payload")
                    self.store.stage_fetched_page(
                        result.page.id,
                        attempts=result.attempts,
                        payload=result.payload,
                    )
                    outcome = "fetched"
                else:
                    self.store.fail_page(
                        result.page.id,
                        attempts=result.attempts,
                        error=result.error_code,
                    )
                    outcome = "failed"

                progress_callback(self.store.terminal_count(job_id))
                self._log_outcome(
                    job_id=job_id,
                    result=result,
                    outcome=outcome,
                )

    async def _fetch(self, page: CrawlPageSnapshot) -> _FetchResult:
        try:
            article = await self.client.fetch_article(page.title)
        except WikipediaRequestError as error:
            return _FetchResult(
                page=page,
                attempts=error.attempts,
                payload=None,
                error_code=error.code,
            )

        try:
            content = self.extractor(article.html)
        except WikipediaExtractionError as error:
            return _FetchResult(
                page=page,
                attempts=article.attempts,
                payload=None,
                error_code=error.code,
            )

        return _FetchResult(
            page=page,
            attempts=article.attempts,
            payload={
                "title": page.title,
                "content": content,
                "url": page.canonical_url,
            },
            error_code=None,
        )

    @staticmethod
    def _log_outcome(
        *,
        job_id: UUID,
        result: _FetchResult,
        outcome: str,
    ) -> None:
        logger.info(
            "wikipedia_page_outcome",
            extra={
                "job_id": str(job_id),
                "phase": "fetch",
                "page_id": result.page.wikipedia_page_id,
                "attempts": result.attempts,
                "position": result.page.position,
                "outcome": outcome,
                "error_code": result.error_code,
            },
        )
