import asyncio
from copy import deepcopy
from dataclasses import dataclass
import logging
from uuid import UUID

import pytest

from app.services.wikipedia_crawl_store import (
    DiscoveryCheckpoint,
    WikipediaCrawlStateError,
    WikipediaCrawlStore,
)
from app.services.wikipedia_discovery import WikipediaDiscoveryRunner
from app.services.wikipedia_types import (
    CrawlCounts,
    CrawlRunSnapshot,
    FrontierSnapshot,
    WikipediaCategoryBatch,
    WikipediaCategoryReference,
    WikipediaPageReference,
    wikipedia_article_url,
)


JOB_ID = UUID("260217d7-6906-42e8-91b8-a6424c797a22")
OTHER_JOB_ID = UUID("9fd24f7f-7fa0-4320-825f-c4cf2d697f47")


@dataclass
class FakeRunRow:
    job_id: UUID
    root_category: str = "Category:Root"
    max_articles: int = 10
    max_depth: int = 1
    discovery_complete: bool = False
    category_limit_reached: bool = False


@dataclass
class FakeFrontierRow:
    id: int
    job_id: UUID
    category_title: str
    depth: int
    continuation: dict | None = None
    status: str = "pending"
    error: str | None = None


@dataclass
class FakePageRow:
    id: int
    job_id: UUID
    position: int
    wikipedia_page_id: int
    title: str
    canonical_url: str
    fetch_status: str = "pending"


@dataclass
class FakeDatabase:
    run: FakeRunRow | None
    frontiers: list[FakeFrontierRow]
    pages: list[FakePageRow]


class FakeSession:
    def __init__(self, database, *, fail_commit=False):
        self.database = database
        self.working = deepcopy(database)
        self.fail_commit = fail_commit
        self.flush_count = 0
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def flush(self):
        self.flush_count += 1

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("simulated commit failure")
        committed = deepcopy(self.working)
        self.database.run = committed.run
        self.database.frontiers = committed.frontiers
        self.database.pages = committed.pages
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeSessionFactory:
    def __init__(self, database):
        self.database = database
        self.fail_next_commit = False
        self.sessions = []

    def __call__(self):
        session = FakeSession(
            self.database,
            fail_commit=self.fail_next_commit,
        )
        self.fail_next_commit = False
        self.sessions.append(session)
        return session


class FakeRepository:
    def __init__(self, session):
        self.session = session
        self.database = session.working

    def get_run(self, job_id):
        run = self.database.run
        if run is None or run.job_id != job_id:
            return None
        return CrawlRunSnapshot(
            job_id=run.job_id,
            root_category=run.root_category,
            max_articles=run.max_articles,
            max_depth=run.max_depth,
            discovery_complete=run.discovery_complete,
            category_limit_reached=run.category_limit_reached,
        )

    def get_run_for_update(self, job_id):
        run = self.database.run
        if run is None or run.job_id != job_id:
            return None
        return run

    def get_frontier_for_update(self, frontier_id):
        return next(
            (
                frontier
                for frontier in self.database.frontiers
                if frontier.id == frontier_id
            ),
            None,
        )

    def get_next_pending_frontier(self, job_id):
        matches = sorted(
            (
                frontier
                for frontier in self.database.frontiers
                if frontier.job_id == job_id and frontier.status == "pending"
            ),
            key=lambda frontier: (frontier.depth, frontier.id),
        )
        if not matches:
            return None
        frontier = matches[0]
        return FrontierSnapshot(
            id=frontier.id,
            category_title=frontier.category_title,
            depth=frontier.depth,
            continuation=deepcopy(frontier.continuation),
        )

    def list_page_ids(self, job_id):
        return {
            page.wikipedia_page_id
            for page in self.database.pages
            if page.job_id == job_id
        }

    def list_category_titles(self, job_id):
        return {
            frontier.category_title
            for frontier in self.database.frontiers
            if frontier.job_id == job_id
        }

    def next_page_position(self, job_id):
        positions = [
            page.position
            for page in self.database.pages
            if page.job_id == job_id
        ]
        return max(positions, default=-1) + 1

    def count_frontier(self, job_id):
        return sum(
            frontier.job_id == job_id
            for frontier in self.database.frontiers
        )

    def count_pages(self, job_id):
        return sum(page.job_id == job_id for page in self.database.pages)

    def has_pending_frontier(self, job_id):
        return any(
            frontier.job_id == job_id and frontier.status == "pending"
            for frontier in self.database.frontiers
        )

    def add_page(
        self,
        job_id,
        *,
        position,
        wikipedia_page_id,
        title,
        canonical_url,
    ):
        page = FakePageRow(
            id=max((page.id for page in self.database.pages), default=0) + 1,
            job_id=job_id,
            position=position,
            wikipedia_page_id=wikipedia_page_id,
            title=title,
            canonical_url=canonical_url,
        )
        self.database.pages.append(page)
        self.session.flush()
        return page

    def add_frontier(self, job_id, *, category_title, depth):
        frontier = FakeFrontierRow(
            id=max(
                (
                    frontier.id
                    for frontier in self.database.frontiers
                ),
                default=0,
            )
            + 1,
            job_id=job_id,
            category_title=category_title,
            depth=depth,
        )
        self.database.frontiers.append(frontier)
        self.session.flush()
        return frontier

    def counts(self, job_id):
        pages = [
            page for page in self.database.pages if page.job_id == job_id
        ]
        visited = sum(
            frontier.job_id == job_id
            and (
                frontier.status in {"completed", "failed"}
                or frontier.continuation is not None
            )
            for frontier in self.database.frontiers
        )
        return CrawlCounts(
            categories_visited=visited,
            discovered=len(pages),
            fetched=0,
            imported=0,
            skipped=0,
            fetch_failed=0,
            ingestion_failed=0,
        )


def make_database(*, max_articles=10, max_depth=1):
    return FakeDatabase(
        run=FakeRunRow(
            job_id=JOB_ID,
            max_articles=max_articles,
            max_depth=max_depth,
        ),
        frontiers=[
            FakeFrontierRow(
                id=1,
                job_id=JOB_ID,
                category_title="Category:Root",
                depth=0,
            )
        ],
        pages=[],
    )


def make_store(database, *, max_categories=100):
    factory = FakeSessionFactory(database)
    store = WikipediaCrawlStore(
        session_factory=factory,
        repository_factory=FakeRepository,
        ingestion_repository_factory=lambda _session: object(),
        max_categories=max_categories,
    )
    return store, factory


def batch(*, pages=(), subcategories=(), continuation=None):
    return WikipediaCategoryBatch(
        pages=tuple(
            WikipediaPageReference(page_id, title)
            for page_id, title in pages
        ),
        subcategories=tuple(
            WikipediaCategoryReference(page_id, title)
            for page_id, title in subcategories
        ),
        continuation=continuation,
    )


def test_duplicate_page_ids_receive_one_deterministic_position():
    database = make_database()
    store, _factory = make_store(database)

    checkpoint = store.checkpoint_discovery(
        JOB_ID,
        1,
        batch(
            pages=(
                (10, "First title"),
                (10, "Duplicate title"),
                (11, "Second title"),
            )
        ),
    )

    assert [page.wikipedia_page_id for page in database.pages] == [10, 11]
    assert [page.position for page in database.pages] == [0, 1]
    assert [page.title for page in database.pages] == [
        "First title",
        "Second title",
    ]
    assert database.pages[0].canonical_url == wikipedia_article_url(
        "First title"
    )
    assert checkpoint.discovered_count == 2


def test_duplicate_category_titles_receive_one_frontier_row():
    database = make_database(max_depth=1)
    store, _factory = make_store(database)

    checkpoint = store.checkpoint_discovery(
        JOB_ID,
        1,
        batch(
            subcategories=(
                (20, "Category:Child"),
                (21, "Category:Child"),
            )
        ),
    )

    assert [frontier.category_title for frontier in database.frontiers] == [
        "Category:Root",
        "Category:Child",
    ]
    assert database.frontiers[1].depth == 1
    assert checkpoint.discovery_complete is False


def test_depth_zero_ignores_subcategories_and_completes():
    database = make_database(max_depth=0)
    store, _factory = make_store(database)

    checkpoint = store.checkpoint_discovery(
        JOB_ID,
        1,
        batch(subcategories=((20, "Category:Child"),)),
    )

    assert len(database.frontiers) == 1
    assert database.frontiers[0].status == "completed"
    assert checkpoint.discovery_complete is True


def test_depth_one_queues_children_but_not_grandchildren():
    database = make_database(max_depth=1)
    database.frontiers.append(
        FakeFrontierRow(
            id=2,
            job_id=JOB_ID,
            category_title="Category:Child",
            depth=1,
        )
    )
    database.frontiers[0].status = "completed"
    store, _factory = make_store(database)

    checkpoint = store.checkpoint_discovery(
        JOB_ID,
        2,
        batch(subcategories=((30, "Category:Grandchild"),)),
    )

    assert len(database.frontiers) == 2
    assert checkpoint.discovery_complete is True


def test_article_limit_stops_at_first_unique_pages_and_keeps_continuation():
    database = make_database(max_articles=2)
    store, _factory = make_store(database)
    continuation = {"cmcontinue": "PRIVATE-NEXT", "continue": "-||"}

    checkpoint = store.checkpoint_discovery(
        JOB_ID,
        1,
        batch(
            pages=((10, "First"), (11, "Second"), (12, "Third")),
            subcategories=((20, "Category:Child"),),
            continuation=continuation,
        ),
    )

    assert [page.wikipedia_page_id for page in database.pages] == [10, 11]
    assert database.frontiers[0].status == "pending"
    assert database.frontiers[0].continuation == continuation
    assert len(database.frontiers) == 1
    assert checkpoint == DiscoveryCheckpoint(
        discovered_count=2,
        discovery_complete=True,
        category_limit_reached=False,
    )


def test_first_category_beyond_limit_sets_flag_but_existing_work_remains():
    database = make_database(max_depth=1)
    store, _factory = make_store(database, max_categories=3)

    checkpoint = store.checkpoint_discovery(
        JOB_ID,
        1,
        batch(
            subcategories=(
                (20, "Category:First"),
                (21, "Category:Second"),
                (22, "Category:Suppressed"),
            )
        ),
    )

    assert [frontier.category_title for frontier in database.frontiers] == [
        "Category:Root",
        "Category:First",
        "Category:Second",
    ]
    assert database.run.category_limit_reached is True
    assert checkpoint.category_limit_reached is True
    assert checkpoint.discovery_complete is False


def test_natural_completion_at_exact_category_limit_leaves_flag_false():
    database = make_database(max_depth=1)
    store, _factory = make_store(database, max_categories=3)

    checkpoint = store.checkpoint_discovery(
        JOB_ID,
        1,
        batch(
            subcategories=(
                (20, "Category:First"),
                (21, "Category:Second"),
            )
        ),
    )

    assert len(database.frontiers) == 3
    assert database.run.category_limit_reached is False
    assert checkpoint.category_limit_reached is False


def test_checkpoint_commits_members_and_continuation_together():
    database = make_database()
    store, factory = make_store(database)
    continuation = {"cmcontinue": "page|next", "continue": "-||"}

    store.checkpoint_discovery(
        JOB_ID,
        1,
        batch(pages=((10, "BM25"),), continuation=continuation),
    )

    assert [page.wikipedia_page_id for page in database.pages] == [10]
    assert database.frontiers[0].continuation == continuation
    assert factory.sessions[-1].committed is True
    assert factory.sessions[-1].closed is True


def test_commit_failure_rolls_back_members_and_continuation():
    database = make_database()
    store, factory = make_store(database)
    factory.fail_next_commit = True

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        store.checkpoint_discovery(
            JOB_ID,
            1,
            batch(
                pages=((10, "BM25"),),
                continuation={"cmcontinue": "not-committed"},
            ),
        )

    assert database.pages == []
    assert database.frontiers[0].continuation is None
    assert factory.sessions[-1].rolled_back is True
    assert factory.sessions[-1].closed is True


def test_read_methods_return_snapshots_after_closing_their_sessions():
    database = make_database()
    store, factory = make_store(database)

    run = store.get_run(JOB_ID)
    counts = store.get_counts(JOB_ID)
    frontier = store.get_next_frontier(JOB_ID)

    assert isinstance(run, CrawlRunSnapshot)
    assert counts.discovered == 0
    assert isinstance(frontier, FrontierSnapshot)
    assert len(factory.sessions) == 3
    assert all(session.closed for session in factory.sessions)


def test_complete_empty_frontier_marks_run_complete_and_returns_count():
    database = make_database()
    database.frontiers[0].status = "completed"
    database.pages.append(
        FakePageRow(
            id=1,
            job_id=JOB_ID,
            position=0,
            wikipedia_page_id=10,
            title="BM25",
            canonical_url=wikipedia_article_url("BM25"),
        )
    )
    store, factory = make_store(database)

    discovered = store.complete_empty_frontier(JOB_ID)

    assert discovered == 1
    assert database.run.discovery_complete is True
    assert factory.sessions[-1].committed is True
    assert factory.sessions[-1].closed is True


def test_complete_empty_frontier_rejects_pending_work():
    database = make_database()
    store, factory = make_store(database)

    with pytest.raises(WikipediaCrawlStateError) as caught:
        store.complete_empty_frontier(JOB_ID)

    assert str(caught.value) == "crawl_state_conflict"
    assert database.run.discovery_complete is False
    assert factory.sessions[-1].rolled_back is True


@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        ("get_run", "crawl_run_not_found"),
        ("get_counts", "crawl_run_not_found"),
        ("get_next_frontier", "crawl_run_not_found"),
        ("complete_empty_frontier", "crawl_run_not_found"),
    ],
)
def test_missing_run_raises_stable_state_error(operation, expected_code):
    database = FakeDatabase(run=None, frontiers=[], pages=[])
    store, factory = make_store(database)

    with pytest.raises(WikipediaCrawlStateError) as caught:
        getattr(store, operation)(JOB_ID)

    assert str(caught.value) == expected_code
    assert factory.sessions[-1].closed is True


def test_checkpoint_rejects_missing_or_foreign_frontier():
    database = make_database()
    database.frontiers[0].job_id = OTHER_JOB_ID
    store, _factory = make_store(database)

    with pytest.raises(WikipediaCrawlStateError) as caught:
        store.checkpoint_discovery(JOB_ID, 1, batch())

    assert str(caught.value) == "crawl_frontier_not_found"


def test_checkpoint_rejects_already_completed_frontier():
    database = make_database()
    database.frontiers[0].status = "completed"
    store, _factory = make_store(database)

    with pytest.raises(WikipediaCrawlStateError) as caught:
        store.checkpoint_discovery(JOB_ID, 1, batch())

    assert str(caught.value) == "crawl_state_conflict"


class RunnerStore:
    def __init__(self, *, complete=False):
        self.complete = complete
        self.frontiers = []
        self.discovered_count = 0
        self.final_discovered_count = 2
        self.checkpoints = []
        self.session_open = False

    def get_run(self, job_id):
        return CrawlRunSnapshot(
            job_id=job_id,
            root_category="Category:Root",
            max_articles=10,
            max_depth=1,
            discovery_complete=self.complete,
            category_limit_reached=False,
        )

    def get_counts(self, _job_id):
        return CrawlCounts(
            categories_visited=0,
            discovered=(
                self.final_discovered_count
                if self.complete
                else self.discovered_count
            ),
            fetched=0,
            imported=0,
            skipped=0,
            fetch_failed=0,
            ingestion_failed=0,
        )

    def get_next_frontier(self, _job_id):
        self.session_open = True
        frontier = self.frontiers.pop(0) if self.frontiers else None
        self.session_open = False
        return frontier

    def checkpoint_discovery(self, job_id, frontier_id, response_batch):
        self.checkpoints.append((job_id, frontier_id, response_batch))
        self.discovered_count += len(response_batch.pages)
        self.complete = not self.frontiers
        if self.complete:
            self.discovered_count = self.final_discovered_count
        return DiscoveryCheckpoint(
            discovered_count=self.discovered_count,
            discovery_complete=self.complete,
            category_limit_reached=False,
        )

    def complete_empty_frontier(self, _job_id):
        self.complete = True
        return self.final_discovered_count


class FakeWikipediaClient:
    def __init__(self, store, responses):
        self.store = store
        self.responses = list(responses)
        self.calls = []

    async def discover_category(self, category, continuation):
        assert self.store.session_open is False
        self.calls.append((category, continuation))
        return self.responses.pop(0)


def test_runner_resumes_continuation_then_moves_breadth_first():
    store = RunnerStore()
    store.frontiers = [
        FrontierSnapshot(
            id=1,
            category_title="Category:Root",
            depth=0,
            continuation={"cmcontinue": "root-next", "continue": "-||"},
        ),
        FrontierSnapshot(
            id=2,
            category_title="Category:Child",
            depth=1,
            continuation=None,
        ),
    ]
    client = FakeWikipediaClient(
        store,
        [
            batch(pages=((10, "First"),)),
            batch(pages=((11, "Second"),)),
        ],
    )

    async def scenario():
        return await WikipediaDiscoveryRunner(store, client).run(JOB_ID)

    count = asyncio.run(scenario())

    assert client.calls == [
        (
            "Category:Root",
            {"cmcontinue": "root-next", "continue": "-||"},
        ),
        ("Category:Child", None),
    ]
    assert count == store.final_discovered_count


def test_previously_complete_run_performs_no_http_request():
    store = RunnerStore(complete=True)
    client = FakeWikipediaClient(store, [])

    async def scenario():
        return await WikipediaDiscoveryRunner(store, client).run(JOB_ID)

    count = asyncio.run(scenario())

    assert count == store.final_discovered_count
    assert client.calls == []


def test_runner_logs_safe_discovery_metadata_without_response(caplog):
    private_response_text = "PRIVATE-ACTION-RESPONSE-731"
    store = RunnerStore()
    store.frontiers = [
        FrontierSnapshot(
            id=1,
            category_title="Category:Root",
            depth=0,
            continuation=None,
        )
    ]
    client = FakeWikipediaClient(
        store,
        [batch(pages=((10, private_response_text),))],
    )
    caplog.set_level(logging.INFO, logger="app.services.wikipedia_discovery")

    async def scenario():
        return await WikipediaDiscoveryRunner(store, client).run(JOB_ID)

    asyncio.run(scenario())

    records = [
        record
        for record in caplog.records
        if record.name == "app.services.wikipedia_discovery"
    ]
    assert {record.getMessage() for record in records} == {
        "wikipedia_discovery_started",
        "wikipedia_discovery_checkpointed",
        "wikipedia_discovery_completed",
    }
    for record in records:
        assert record.job_id == str(JOB_ID)
        assert record.phase == "discovery"
        assert isinstance(record.category, str)
        assert isinstance(record.depth, int)
        assert isinstance(record.outcome, str)
        assert isinstance(record.discovered_count, int)
    assert private_response_text not in "\n".join(
        f"{record.getMessage()} {record.__dict__!r}" for record in records
    )
