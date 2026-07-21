import asyncio
from datetime import timezone
import logging
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from app.services.wikipedia_client import WikipediaPermanentError
from app.services.wikipedia_crawl_store import (
    WikipediaCrawlStateError,
    WikipediaCrawlStore,
)
from app.services.wikipedia_extraction import WikipediaExtractionError
from app.services.wikipedia_fetching import WikipediaFetchRunner
from app.services.wikipedia_types import (
    CrawlCounts,
    CrawlPageSnapshot,
    CrawlRunSnapshot,
    FetchedWikipediaArticle,
)


JOB_ID = UUID("32cb28a0-1e7b-4d82-93e9-a70d4d43497c")
FIRST_PAGE = CrawlPageSnapshot(
    id=101,
    position=0,
    wikipedia_page_id=10,
    title="First article",
    canonical_url="https://en.wikipedia.org/wiki/First_article",
)
SECOND_PAGE = CrawlPageSnapshot(
    id=102,
    position=1,
    wikipedia_page_id=11,
    title="Second article",
    canonical_url="https://en.wikipedia.org/wiki/Second_article",
)


class FakeFetchStore:
    def __init__(self):
        self.pending_batches = []
        self.list_limits = []
        self.staged = []
        self.failed = []
        self.terminal = 0
        self.session_open = False

    def list_pending_pages(self, _job_id, *, limit=20):
        self.list_limits.append(limit)
        self.session_open = True
        pages = self.pending_batches.pop(0) if self.pending_batches else []
        self.session_open = False
        return pages

    def stage_fetched_page(self, page_id, *, attempts, payload):
        self.staged.append((page_id, attempts, payload))
        self.terminal += 1

    def fail_page(self, page_id, *, attempts, error):
        self.failed.append((page_id, attempts, error))
        self.terminal += 1

    def terminal_count(self, _job_id):
        return self.terminal


class ConcurrentWikipediaClient:
    def __init__(self, store, *, expected_starts=2):
        self.store = store
        self.expected_starts = expected_starts
        self.started = []
        self.started_before_release = []
        self.release = asyncio.Event()

    async def fetch_article(self, title):
        assert self.store.session_open is False
        self.started.append(title)
        if len(self.started) == self.expected_starts:
            self.started_before_release = list(self.started)
            self.release.set()
        await self.release.wait()
        return FetchedWikipediaArticle(
            title=title,
            canonical_url="https://en.wikipedia.org/wiki/source",
            html=(
                "first html" if title == FIRST_PAGE.title else "second html"
            ),
            attempts=1,
        )


class ImmediateWikipediaClient:
    def __init__(self, store, outcomes=None):
        self.store = store
        self.outcomes = outcomes or {}
        self.calls = []

    async def fetch_article(self, title):
        assert self.store.session_open is False
        self.calls.append(title)
        outcome = self.outcomes.get(title)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            return outcome
        return FetchedWikipediaArticle(
            title=title,
            canonical_url="https://en.wikipedia.org/wiki/source",
            html=f"html for {title}",
            attempts=1,
        )


def test_fetches_batch_concurrently_then_stages_normalized_payloads():
    store = FakeFetchStore()
    store.pending_batches = [[FIRST_PAGE, SECOND_PAGE], []]
    client = ConcurrentWikipediaClient(store)
    progress = []

    async def scenario():
        await WikipediaFetchRunner(
            store,
            client,
            extractor=lambda html: f"normalized {html} content long enough",
        ).run(JOB_ID, progress_callback=progress.append)

    asyncio.run(scenario())

    assert client.started_before_release == [
        FIRST_PAGE.title,
        SECOND_PAGE.title,
    ]
    assert store.staged == [
        (
            FIRST_PAGE.id,
            1,
            {
                "title": FIRST_PAGE.title,
                "content": "normalized first html content long enough",
                "url": FIRST_PAGE.canonical_url,
            },
        ),
        (
            SECOND_PAGE.id,
            1,
            {
                "title": SECOND_PAGE.title,
                "content": "normalized second html content long enough",
                "url": SECOND_PAGE.canonical_url,
            },
        ),
    ]
    assert progress == [1, 2]


def test_at_most_twenty_pages_are_scheduled_per_gather_batch():
    pages = [
        CrawlPageSnapshot(
            id=index,
            position=index,
            wikipedia_page_id=1000 + index,
            title=f"Article {index}",
            canonical_url=f"https://en.wikipedia.org/wiki/Article_{index}",
        )
        for index in range(25)
    ]
    store = FakeFetchStore()
    store.pending_batches = [pages, []]
    client = ImmediateWikipediaClient(store)

    async def scenario():
        await WikipediaFetchRunner(
            store,
            client,
            extractor=lambda html: f"normalized {html}",
        ).run(JOB_ID, progress_callback=lambda _count: None)

    asyncio.run(scenario())

    assert store.list_limits == [20, 20]
    assert client.calls == [page.title for page in pages[:20]]
    assert len(store.staged) == 20


def test_request_error_becomes_one_terminal_fetch_failure():
    store = FakeFetchStore()
    store.pending_batches = [[FIRST_PAGE], []]
    client = ImmediateWikipediaClient(
        store,
        {
            FIRST_PAGE.title: WikipediaPermanentError(
                "wikipedia_not_found",
                attempts=2,
            )
        },
    )
    progress = []

    async def scenario():
        await WikipediaFetchRunner(store, client).run(
            JOB_ID,
            progress_callback=progress.append,
        )

    asyncio.run(scenario())

    assert store.staged == []
    assert store.failed == [(FIRST_PAGE.id, 2, "wikipedia_not_found")]
    assert progress == [1]


def test_extraction_error_uses_successful_http_attempt_count():
    store = FakeFetchStore()
    store.pending_batches = [[FIRST_PAGE], []]
    client = ImmediateWikipediaClient(
        store,
        {
            FIRST_PAGE.title: FetchedWikipediaArticle(
                title=FIRST_PAGE.title,
                canonical_url=FIRST_PAGE.canonical_url,
                html="short",
                attempts=3,
            )
        },
    )

    def fail_extraction(_html):
        raise WikipediaExtractionError("content_too_short")

    async def scenario():
        await WikipediaFetchRunner(
            store,
            client,
            extractor=fail_extraction,
        ).run(JOB_ID, progress_callback=lambda _count: None)

    asyncio.run(scenario())

    assert store.failed == [(FIRST_PAGE.id, 3, "content_too_short")]


@pytest.mark.parametrize("failure_source", ["client", "extractor"])
def test_unexpected_exceptions_propagate_and_leave_batch_pending(
    failure_source,
):
    store = FakeFetchStore()
    store.pending_batches = [[FIRST_PAGE]]
    unexpected = RuntimeError("unexpected private failure")
    outcomes = (
        {FIRST_PAGE.title: unexpected}
        if failure_source == "client"
        else None
    )
    client = ImmediateWikipediaClient(store, outcomes)

    def extractor(html):
        if failure_source == "extractor":
            raise unexpected
        return html

    async def scenario():
        await WikipediaFetchRunner(
            store,
            client,
            extractor=extractor,
        ).run(JOB_ID, progress_callback=lambda _count: None)

    with pytest.raises(RuntimeError, match="unexpected private failure"):
        asyncio.run(scenario())

    assert store.staged == []
    assert store.failed == []
    assert store.terminal == 0


class DurableFakeFetchStore(FakeFetchStore):
    def __init__(self, pages):
        super().__init__()
        self.pending = {page.id: page for page in pages}

    def list_pending_pages(self, _job_id, *, limit=20):
        self.list_limits.append(limit)
        self.session_open = True
        pages = sorted(self.pending.values(), key=lambda page: page.position)[
            :limit
        ]
        self.session_open = False
        return pages

    def stage_fetched_page(self, page_id, *, attempts, payload):
        super().stage_fetched_page(
            page_id,
            attempts=attempts,
            payload=payload,
        )
        self.pending.pop(page_id, None)

    def fail_page(self, page_id, *, attempts, error):
        super().fail_page(page_id, attempts=attempts, error=error)
        self.pending.pop(page_id, None)


def test_redelivery_never_refetches_or_restages_terminal_pages():
    store = DurableFakeFetchStore([FIRST_PAGE])
    client = ImmediateWikipediaClient(store)
    runner = WikipediaFetchRunner(
        store,
        client,
        extractor=lambda html: f"normalized {html}",
    )

    async def scenario():
        await runner.run(JOB_ID, progress_callback=lambda _count: None)
        await runner.run(JOB_ID, progress_callback=lambda _count: None)

    asyncio.run(scenario())

    assert client.calls == [FIRST_PAGE.title]
    assert len(store.staged) == 1


def test_page_outcome_logs_exclude_html_and_extracted_content(caplog):
    private_html = "PRIVATE-HTML-731"
    private_content = "PRIVATE-EXTRACTED-CONTENT-947"
    store = FakeFetchStore()
    store.pending_batches = [[FIRST_PAGE], []]
    client = ImmediateWikipediaClient(
        store,
        {
            FIRST_PAGE.title: FetchedWikipediaArticle(
                title=FIRST_PAGE.title,
                canonical_url=FIRST_PAGE.canonical_url,
                html=private_html,
                attempts=2,
            )
        },
    )
    caplog.set_level(logging.INFO, logger="app.services.wikipedia_fetching")

    async def scenario():
        await WikipediaFetchRunner(
            store,
            client,
            extractor=lambda _html: private_content,
        ).run(JOB_ID, progress_callback=lambda _count: None)

    asyncio.run(scenario())

    records = [
        record
        for record in caplog.records
        if record.name == "app.services.wikipedia_fetching"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == "wikipedia_page_outcome"
    assert record.job_id == str(JOB_ID)
    assert record.phase == "fetch"
    assert record.page_id == FIRST_PAGE.wikipedia_page_id
    assert record.attempts == 2
    assert record.position == FIRST_PAGE.position
    assert record.outcome == "fetched"
    assert record.error_code is None
    serialized = f"{record.getMessage()} {record.__dict__!r}"
    assert private_html not in serialized
    assert private_content not in serialized


def crawl_run_snapshot():
    return CrawlRunSnapshot(
        job_id=JOB_ID,
        root_category="Category:Root",
        max_articles=10,
        max_depth=0,
        discovery_complete=True,
        category_limit_reached=False,
    )


def store_with_mocks(*, page=None, pending_pages=None, counts=None):
    session = Mock()
    repository = Mock()
    repository.get_run.return_value = crawl_run_snapshot()
    repository.get_page_for_update.return_value = page
    repository.list_pending_pages.return_value = pending_pages or []
    repository.counts.return_value = counts or CrawlCounts(
        categories_visited=1,
        discovered=0,
        fetched=0,
        imported=0,
        skipped=0,
        fetch_failed=0,
        ingestion_failed=0,
    )
    ingestion_repository = Mock()
    store = WikipediaCrawlStore(
        session_factory=lambda: session,
        repository_factory=lambda _session: repository,
        ingestion_repository_factory=lambda _session: ingestion_repository,
        max_categories=100,
    )
    return store, session, repository, ingestion_repository


def pending_page_row():
    return SimpleNamespace(
        id=FIRST_PAGE.id,
        job_id=JOB_ID,
        position=FIRST_PAGE.position,
        fetch_status="pending",
    )


def test_store_lists_pending_pages_with_bound_and_closes_session():
    store, session, repository, _ingestion = store_with_mocks(
        pending_pages=[FIRST_PAGE]
    )

    pages = store.list_pending_pages(JOB_ID, limit=7)

    assert pages == [FIRST_PAGE]
    repository.list_pending_pages.assert_called_once_with(JOB_ID, limit=7)
    session.close.assert_called_once_with()


def test_store_stages_ingestion_and_fetch_transition_atomically():
    page = pending_page_row()
    store, session, repository, ingestion = store_with_mocks(page=page)
    payload = {
        "title": FIRST_PAGE.title,
        "content": "normalized content",
        "url": FIRST_PAGE.canonical_url,
    }
    ingestion.stage_at_position.return_value = SimpleNamespace(id=501)
    repository.mark_page_fetched.return_value = page

    store.stage_fetched_page(FIRST_PAGE.id, attempts=2, payload=payload)

    ingestion.stage_at_position.assert_called_once_with(
        JOB_ID,
        FIRST_PAGE.position,
        payload,
    )
    call = repository.mark_page_fetched.call_args
    assert call.args == (FIRST_PAGE.id,)
    assert call.kwargs["attempts"] == 2
    assert call.kwargs["ingestion_item_id"] == 501
    assert call.kwargs["fetched_at"].tzinfo == timezone.utc
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()


def test_store_does_not_restage_an_already_terminal_page():
    page = pending_page_row()
    page.fetch_status = "fetched"
    store, session, repository, ingestion = store_with_mocks(page=page)

    store.stage_fetched_page(FIRST_PAGE.id, attempts=2, payload={})

    ingestion.stage_at_position.assert_not_called()
    repository.mark_page_fetched.assert_not_called()
    session.commit.assert_called_once_with()
    session.close.assert_called_once_with()


def test_store_sanitizes_failure_and_commits_guarded_transition():
    page = pending_page_row()
    store, session, repository, _ingestion = store_with_mocks(page=page)
    repository.mark_page_failed.return_value = page

    store.fail_page(FIRST_PAGE.id, attempts=3, error="x" * 400)

    repository.mark_page_failed.assert_called_once_with(
        FIRST_PAGE.id,
        attempts=3,
        error="x" * 300,
    )
    session.commit.assert_called_once_with()
    session.close.assert_called_once_with()


@pytest.mark.parametrize("operation", ["stage", "fail"])
def test_store_raises_stable_error_for_missing_page(operation):
    store, session, _repository, _ingestion = store_with_mocks(page=None)

    with pytest.raises(WikipediaCrawlStateError) as caught:
        if operation == "stage":
            store.stage_fetched_page(999, attempts=1, payload={})
        else:
            store.fail_page(999, attempts=1, error="missing")

    assert str(caught.value) == "crawl_page_not_found"
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


@pytest.mark.parametrize("operation", ["stage", "fail"])
def test_store_rolls_back_when_guarded_page_transition_loses(operation):
    page = pending_page_row()
    store, session, repository, ingestion = store_with_mocks(page=page)
    ingestion.stage_at_position.return_value = SimpleNamespace(id=501)
    repository.mark_page_fetched.return_value = None
    repository.mark_page_failed.return_value = None

    with pytest.raises(WikipediaCrawlStateError) as caught:
        if operation == "stage":
            store.stage_fetched_page(101, attempts=1, payload={})
        else:
            store.fail_page(101, attempts=1, error="failed")

    assert str(caught.value) == "crawl_state_conflict"
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()
    session.close.assert_called_once_with()


def test_store_terminal_count_includes_fetched_and_fetch_failed_pages():
    counts = CrawlCounts(
        categories_visited=1,
        discovered=4,
        fetched=3,
        imported=0,
        skipped=0,
        fetch_failed=1,
        ingestion_failed=0,
    )
    store, session, _repository, _ingestion = store_with_mocks(counts=counts)

    terminal = store.terminal_count(JOB_ID)

    assert terminal == 4
    session.close.assert_called_once_with()
