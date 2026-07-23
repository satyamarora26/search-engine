from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.models.crawl import (
    COMPLETED_FRONTIER_STATUS,
    CrawlFrontier,
    CrawlItem,
    CrawlRun,
)
from app.models.ingestion_item import IMPORTED_ITEM_STATUS
from app.repositories.crawls import CrawlRepository
from app.services.crawl_types import (
    CrawlCounts,
    CrawlItemView,
    CrawlRunSnapshot,
    DiscoveryCheckpoint,
    DiscoveredItem,
    FrontierSnapshot,
)

JOB_ID = UUID("0ea30c3d-273f-44cc-a43f-489c2ece940d")
FETCHED_AT = datetime(2026, 7, 23, tzinfo=timezone.utc)


class FakeScalarResult:
    def __init__(self, *, one=None, all_=None) -> None:
        self._one = one
        self._all = [] if all_ is None else all_

    def one_or_none(self):
        return self._one

    def all(self):
        return self._all


class FakeExecuteResult:
    def __init__(self, *, one=None, all_=None) -> None:
        self._one = one
        self._all = [] if all_ is None else all_

    def one(self):
        return self._one

    def all(self):
        return self._all


class FakeSession:
    def __init__(
        self,
        *,
        scalar_result=None,
        scalar_value=None,
        scalar_results=None,
        scalar_values=None,
        execute_result=None,
    ) -> None:
        self.scalar_result = scalar_result or FakeScalarResult()
        self.scalar_value = scalar_value
        self.scalar_results = list(scalar_results or [])
        self.scalar_values = list(scalar_values or [])
        self.execute_result = execute_result or FakeExecuteResult()
        self.added = []
        self.flushed = False
        self.statements = []

    def add(self, instance) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        self.flushed = True

    def scalars(self, statement):
        self.statements.append(statement)
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return self.scalar_result

    def scalar(self, statement):
        self.statements.append(statement)
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return self.scalar_value

    def execute(self, statement):
        self.statements.append(statement)
        return self.execute_result


def compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_create_run_and_frontier_flush_durable_rows():
    session = FakeSession()
    repository = CrawlRepository(session)

    run = repository.create_run(
        JOB_ID,
        source_key="medium",
        seed_url="https://medium.com/towards-data-science",
        max_articles=25,
        max_depth=0,
    )
    frontier = repository.add_frontier(
        JOB_ID,
        locator="https://medium.com/feed/towards-data-science",
        depth=0,
    )

    assert session.added == [run, frontier]
    assert session.flushed is True
    assert run.source_key == "medium"
    assert run.seed_url.endswith("towards-data-science")
    assert frontier.status == "pending"


def test_get_run_and_frontier_return_frozen_source_neutral_snapshots():
    run = CrawlRun(
        job_id=JOB_ID,
        source_key="medium",
        seed_url="https://medium.com/towards-data-science",
        max_articles=30,
        max_depth=0,
        discovery_complete=False,
        limit_reached=True,
    )
    frontier = CrawlFrontier(
        id=7,
        job_id=JOB_ID,
        locator="https://medium.com/sitemap.xml",
        depth=0,
        continuation={"offset": 10},
    )
    session = FakeSession(scalar_result=FakeScalarResult(one=run))
    repository = CrawlRepository(session)

    assert repository.get_run(JOB_ID) == CrawlRunSnapshot(
        job_id=JOB_ID,
        source_key="medium",
        seed_url="https://medium.com/towards-data-science",
        max_articles=30,
        max_depth=0,
        discovery_complete=False,
        limit_reached=True,
    )

    session.scalar_result = FakeScalarResult(one=frontier)
    assert repository.get_next_pending_frontier(JOB_ID) == FrontierSnapshot(
        id=7,
        locator="https://medium.com/sitemap.xml",
        depth=0,
        continuation={"offset": 10},
    )
    sql = compile_sql(session.statements[-1])
    assert "status = 'pending'" in sql
    assert "ORDER BY crawl_frontier.depth ASC" in sql
    assert "crawl_frontier.id ASC" in sql
    assert "LIMIT 1" in sql


def test_item_transitions_are_guarded_by_pending_status():
    updated = CrawlItem(
        id=9,
        job_id=JOB_ID,
        position=3,
        source_item_id="article-3",
        discovered_url="https://medium.com/towards-data-science/article-3",
        canonical_url="https://medium.com/towards-data-science/article-3",
        title="BM25",
        fetch_status="failed",
        fetch_attempts=3,
        error="medium_not_found",
    )
    session = FakeSession(scalar_result=FakeScalarResult(one=updated))
    repository = CrawlRepository(session)

    assert repository.mark_item_failed(
        9,
        attempts=3,
        error="medium_not_found",
    ) is updated

    sql = compile_sql(session.statements[0])
    assert "crawl_items.id = 9" in sql
    assert "crawl_items.fetch_status = 'pending'" in sql
    assert "RETURNING" in sql


def test_fetched_transition_sets_document_link_attempts_and_timestamp():
    updated = CrawlItem(
        id=9,
        job_id=JOB_ID,
        position=3,
        discovered_url="https://medium.com/towards-data-science/article-3",
        canonical_url="https://medium.com/towards-data-science/article-3",
        title="BM25",
    )
    session = FakeSession(scalar_result=FakeScalarResult(one=updated))

    assert CrawlRepository(session).mark_item_fetched(
        9,
        attempts=2,
        ingestion_item_id=81,
        fetched_at=FETCHED_AT,
    ) is updated

    sql = compile_sql(session.statements[0]).replace(" ", "")
    assert "fetch_status='fetched'" in sql
    assert "fetch_attempts=2" in sql
    assert "ingestion_item_id=81" in sql


def test_counts_map_generic_fetch_and_ingestion_outcomes():
    session = FakeSession(
        execute_result=FakeExecuteResult(one=(4, 3, 2, 1, 1, 0))
    )

    counts = CrawlRepository(session).counts(JOB_ID)

    assert counts == CrawlCounts(
        discovered=4,
        fetched=3,
        imported=2,
        skipped=1,
        fetch_failed=1,
        ingestion_failed=0,
    )
    assert counts.failed == 1
    assert counts.terminal == 4


def test_item_view_query_outer_joins_ingestion_outcomes_and_paginates():
    session = FakeSession(
        execute_result=FakeExecuteResult(
            all_=[
                (
                    3,
                    "article-3",
                    "BM25",
                    "https://medium.com/towards-data-science/article-3",
                    "fetched",
                    IMPORTED_ITEM_STATUS,
                    81,
                    None,
                )
            ]
        )
    )

    result = CrawlRepository(session).list_item_views(
        JOB_ID,
        limit=25,
        offset=50,
    )

    assert result == [
        CrawlItemView(
            position=3,
            source_item_id="article-3",
            title="BM25",
            url="https://medium.com/towards-data-science/article-3",
            fetch_status="fetched",
            ingestion_status=IMPORTED_ITEM_STATUS,
            document_id=81,
            error=None,
        )
    ]
    sql = compile_sql(session.statements[0])
    assert "LEFT OUTER JOIN ingestion_items" in sql
    assert "coalesce(crawl_items.error, ingestion_items.error)" in sql
    assert "ORDER BY crawl_items.position ASC" in sql
    assert "LIMIT 25" in sql
    assert "OFFSET 50" in sql


def test_discovery_checkpoint_adds_unique_items_and_completes_frontier():
    run = CrawlRun(
        job_id=JOB_ID,
        source_key="medium",
        seed_url="https://medium.com/towards-data-science",
        max_articles=2,
        max_depth=0,
        discovery_complete=False,
        limit_reached=False,
    )
    frontier = CrawlFrontier(
        id=7,
        job_id=JOB_ID,
        locator="https://medium.com/feed/towards-data-science",
        depth=0,
        continuation=None,
        status="pending",
    )
    session = FakeSession(
        scalar_results=[
            FakeScalarResult(one=run),
            FakeScalarResult(one=frontier),
            FakeScalarResult(all_=[]),
        ],
        scalar_values=[0, 2],
    )
    repository = CrawlRepository(session)

    checkpoint = repository.checkpoint_discovery(
        JOB_ID,
        frontier.id,
        [
            DiscoveredItem(
                source_item_id="one",
                title="One",
                discovered_url="https://medium.com/towards-data-science/one",
                canonical_url="https://medium.com/towards-data-science/one",
            ),
            DiscoveredItem(
                source_item_id="two",
                title="Two",
                discovered_url="https://medium.com/towards-data-science/two",
                canonical_url="https://medium.com/towards-data-science/two",
            ),
            DiscoveredItem(
                source_item_id="three",
                title="Three",
                discovered_url="https://medium.com/towards-data-science/three",
                canonical_url="https://medium.com/towards-data-science/three",
            ),
        ],
        continuation=None,
    )

    assert checkpoint == DiscoveryCheckpoint(
        discovered_count=2,
        discovery_complete=True,
        limit_reached=True,
    )
    assert run.discovery_complete is True
    assert run.limit_reached is True
    assert frontier.status == COMPLETED_FRONTIER_STATUS
    assert [item.position for item in session.added] == [0, 1]
