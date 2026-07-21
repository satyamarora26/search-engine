from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from app.models.ingestion_item import IMPORTED_ITEM_STATUS
from app.models.wikipedia_crawl import (
    PENDING_FETCH_STATUS,
    WikipediaCrawlFrontier,
    WikipediaCrawlPage,
    WikipediaCrawlRun,
)
from app.repositories.wikipedia_crawls import WikipediaCrawlRepository
from app.services.wikipedia_types import (
    CrawlCounts,
    CrawlItemView,
    CrawlPageSnapshot,
    CrawlRunSnapshot,
    FrontierSnapshot,
    wikipedia_article_url,
)

JOB_ID = UUID("0ea30c3d-273f-44cc-a43f-489c2ece940d")
FETCHED_AT = datetime(2026, 7, 21, tzinfo=timezone.utc)


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
        execute_result=None,
    ) -> None:
        self.scalar_result = scalar_result or FakeScalarResult()
        self.scalar_value = scalar_value
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
        return self.scalar_result

    def scalar(self, statement):
        self.statements.append(statement)
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


def test_canonical_article_url_encodes_path_characters_deterministically():
    assert wikipedia_article_url("Cafe search / ranking?") == (
        "https://en.wikipedia.org/wiki/Cafe_search_%2F_ranking%3F"
    )


def test_create_run_and_frontier_flush_durable_rows():
    session = FakeSession()
    repository = WikipediaCrawlRepository(session)

    run = repository.create_run(
        JOB_ID,
        root_category="Category:Featured articles",
        max_articles=25,
        max_depth=1,
    )
    frontier = repository.add_frontier(
        JOB_ID,
        category_title="Category:Featured articles",
        depth=0,
    )

    assert session.added == [run, frontier]
    assert session.flushed is True
    assert run.job_id == JOB_ID
    assert frontier.status == "pending"


def test_get_run_returns_frozen_snapshot():
    model = WikipediaCrawlRun(
        job_id=JOB_ID,
        root_category="Category:Physics",
        max_articles=30,
        max_depth=1,
        discovery_complete=False,
        category_limit_reached=True,
    )
    session = FakeSession(scalar_result=FakeScalarResult(one=model))

    result = WikipediaCrawlRepository(session).get_run(JOB_ID)

    assert result == CrawlRunSnapshot(
        job_id=JOB_ID,
        root_category="Category:Physics",
        max_articles=30,
        max_depth=1,
        discovery_complete=False,
        category_limit_reached=True,
    )


def test_next_frontier_uses_breadth_first_stable_order():
    model = WikipediaCrawlFrontier(
        id=7,
        job_id=JOB_ID,
        category_title="Category:Search",
        depth=1,
        continuation=None,
    )
    session = FakeSession(scalar_result=FakeScalarResult(one=model))
    repository = WikipediaCrawlRepository(session)

    result = repository.get_next_pending_frontier(JOB_ID)

    assert result == FrontierSnapshot(
        id=7,
        category_title="Category:Search",
        depth=1,
        continuation=None,
    )
    sql = compile_sql(session.statements[0])
    assert "status = 'pending'" in sql
    assert "ORDER BY wikipedia_crawl_frontier.depth ASC" in sql
    assert "wikipedia_crawl_frontier.id ASC" in sql
    assert "LIMIT 1" in sql


def test_pending_pages_use_discovery_order_and_bound():
    model = WikipediaCrawlPage(
        id=9,
        job_id=JOB_ID,
        position=3,
        wikipedia_page_id=42,
        title="BM25",
        canonical_url="https://en.wikipedia.org/wiki/BM25",
    )
    session = FakeSession(scalar_result=FakeScalarResult(all_=[model]))
    repository = WikipediaCrawlRepository(session)

    result = repository.list_pending_pages(JOB_ID, limit=20)

    assert result == [
        CrawlPageSnapshot(
            id=9,
            position=3,
            wikipedia_page_id=42,
            title="BM25",
            canonical_url="https://en.wikipedia.org/wiki/BM25",
        )
    ]
    sql = compile_sql(session.statements[0])
    assert "fetch_status = 'pending'" in sql
    assert "ORDER BY wikipedia_crawl_pages.position ASC" in sql
    assert "LIMIT 20" in sql


def test_fetch_transitions_are_guarded_by_pending_status():
    updated = WikipediaCrawlPage(
        id=9,
        job_id=JOB_ID,
        position=3,
        wikipedia_page_id=42,
        title="BM25",
        canonical_url="https://en.wikipedia.org/wiki/BM25",
        fetch_status="failed",
        fetch_attempts=3,
        error="wikipedia_not_found",
    )
    session = FakeSession(scalar_result=FakeScalarResult(one=updated))
    repository = WikipediaCrawlRepository(session)

    assert repository.mark_page_failed(
        9,
        attempts=3,
        error="wikipedia_not_found",
    ) is updated

    sql = compile_sql(session.statements[0])
    assert "wikipedia_crawl_pages.id = 9" in sql
    assert "wikipedia_crawl_pages.fetch_status = 'pending'" in sql
    assert "RETURNING" in sql


def test_fetched_transition_sets_link_attempts_and_timestamp():
    updated = WikipediaCrawlPage(
        id=9,
        job_id=JOB_ID,
        position=3,
        wikipedia_page_id=42,
        title="BM25",
        canonical_url="https://en.wikipedia.org/wiki/BM25",
    )
    session = FakeSession(scalar_result=FakeScalarResult(one=updated))

    assert WikipediaCrawlRepository(session).mark_page_fetched(
        9,
        attempts=2,
        ingestion_item_id=81,
        fetched_at=FETCHED_AT,
    ) is updated

    sql = compile_sql(session.statements[0])
    assert "fetch_status='fetched'" in sql.replace(" ", "")
    assert "fetch_attempts=2" in sql.replace(" ", "")
    assert "ingestion_item_id=81" in sql.replace(" ", "")


def test_counts_map_one_aggregate_row_and_encode_visit_rules():
    session = FakeSession(
        execute_result=FakeExecuteResult(one=(2, 4, 3, 2, 1, 1, 0))
    )

    counts = WikipediaCrawlRepository(session).counts(JOB_ID)

    assert counts == CrawlCounts(
        categories_visited=2,
        discovered=4,
        fetched=3,
        imported=2,
        skipped=1,
        fetch_failed=1,
        ingestion_failed=0,
    )
    assert counts.failed == 1
    assert counts.terminal == 4
    sql = compile_sql(session.statements[0])
    assert "continuation IS NOT NULL" in sql
    assert "status IN ('completed', 'failed')" in sql
    assert "LEFT OUTER JOIN ingestion_items" in sql


def test_item_view_query_outer_joins_outcomes_and_paginates():
    session = FakeSession(
        execute_result=FakeExecuteResult(
            all_=[
                (
                    3,
                    42,
                    "BM25",
                    "https://en.wikipedia.org/wiki/BM25",
                    "fetched",
                    IMPORTED_ITEM_STATUS,
                    81,
                    None,
                )
            ]
        )
    )
    repository = WikipediaCrawlRepository(session)

    result = repository.list_item_views(JOB_ID, limit=25, offset=50)

    assert result == [
        CrawlItemView(
            position=3,
            wikipedia_page_id=42,
            title="BM25",
            url="https://en.wikipedia.org/wiki/BM25",
            fetch_status="fetched",
            ingestion_status=IMPORTED_ITEM_STATUS,
            document_id=81,
            error=None,
        )
    ]
    sql = compile_sql(session.statements[0])
    assert "LEFT OUTER JOIN ingestion_items" in sql
    assert "coalesce(wikipedia_crawl_pages.error, ingestion_items.error)" in sql
    assert "ORDER BY wikipedia_crawl_pages.position ASC" in sql
    assert "LIMIT 25" in sql
    assert "OFFSET 50" in sql


@pytest.mark.parametrize(
    ("method", "kwargs", "message"),
    [
        ("list_pending_pages", {"limit": 0}, "limit must be at least 1"),
        (
            "list_item_views",
            {"limit": 1, "offset": -1},
            "offset cannot be negative",
        ),
    ],
)
def test_bounded_queries_reject_invalid_pagination_without_sql(
    method,
    kwargs,
    message,
):
    session = FakeSession()
    repository = WikipediaCrawlRepository(session)

    with pytest.raises(ValueError, match=message):
        getattr(repository, method)(JOB_ID, **kwargs)

    assert session.statements == []
