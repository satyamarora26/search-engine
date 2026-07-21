import os
from queue import Queue
from threading import Barrier, Thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.ingestion_item import IngestionItem
from app.models.job import WIKIPEDIA_CRAWL_JOB, Job
from app.models.wikipedia_crawl import (
    FAILED_FETCH_STATUS,
    FETCHED_FETCH_STATUS,
    PENDING_FETCH_STATUS,
    WikipediaCrawlFrontier,
    WikipediaCrawlPage,
    WikipediaCrawlRun,
)
from app.repositories.documents import DocumentRepository
from app.repositories.ingestion_items import IngestionItemRepository
from app.repositories.wikipedia_crawls import WikipediaCrawlRepository
from app.services.wikipedia_crawl_store import WikipediaCrawlStore
from app.services.wikipedia_types import (
    WikipediaCategoryBatch,
    WikipediaCategoryReference,
    WikipediaPageReference,
)


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL tests",
    ),
]


@pytest.fixture
def db_session():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(Job))
    session.flush()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def session_factory_for(db_session):
    connection = db_session.connection()
    return lambda: Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )


def create_crawl(
    session,
    *,
    max_articles=10,
    max_depth=1,
    root_category="Category:Root",
):
    job = Job(
        id=uuid4(),
        job_type=WIKIPEDIA_CRAWL_JOB,
        progress_current=0,
        progress_total=None,
    )
    session.add(job)
    session.flush()
    repository = WikipediaCrawlRepository(session)
    run = repository.create_run(
        job.id,
        root_category=root_category,
        max_articles=max_articles,
        max_depth=max_depth,
    )
    frontier = repository.add_frontier(
        job.id,
        category_title=root_category,
        depth=0,
    )
    return job, run, frontier


def category_batch(*, pages=(), subcategories=(), continuation=None):
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


@pytest.mark.parametrize(
    "page_values",
    [
        {"position": -1},
        {"fetch_attempts": -1},
        {"fetch_status": "unknown"},
        {"fetch_status": "fetched", "ingestion_item_id": None},
        {"fetch_status": "failed", "error": None},
    ],
)
def test_database_rejects_invalid_page_state(db_session, page_values):
    job, _run, _frontier = create_crawl(db_session)
    values = {
        "job_id": job.id,
        "position": 0,
        "wikipedia_page_id": 10,
        "title": "Invalid page",
        "canonical_url": "https://en.wikipedia.org/wiki/Invalid_page",
        "fetch_status": PENDING_FETCH_STATUS,
        "fetch_attempts": 0,
    }
    values.update(page_values)
    db_session.add(WikipediaCrawlPage(**values))

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "duplicate",
    ["category_title", "position", "wikipedia_page_id"],
)
def test_database_rejects_duplicate_crawl_identity(db_session, duplicate):
    job, _run, _frontier = create_crawl(db_session)
    if duplicate == "category_title":
        db_session.add(
            WikipediaCrawlFrontier(
                job_id=job.id,
                category_title="Category:Root",
                depth=1,
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()
        return

    first = WikipediaCrawlPage(
        job_id=job.id,
        position=0,
        wikipedia_page_id=10,
        title="First",
        canonical_url="https://en.wikipedia.org/wiki/First",
    )
    second = WikipediaCrawlPage(
        job_id=job.id,
        position=0 if duplicate == "position" else 1,
        wikipedia_page_id=10 if duplicate == "wikipedia_page_id" else 11,
        title="Second",
        canonical_url="https://en.wikipedia.org/wiki/Second",
    )
    db_session.add_all([first, second])

    with pytest.raises(IntegrityError):
        db_session.flush()


def create_committed_race_crawl() -> UUID:
    job_id = uuid4()
    with SessionLocal() as session:
        session.add(
            Job(
                id=job_id,
                job_type=WIKIPEDIA_CRAWL_JOB,
                progress_current=0,
                progress_total=None,
            )
        )
        session.add(
            WikipediaCrawlRun(
                job_id=job_id,
                root_category="Category:Race root",
                max_articles=10,
                max_depth=1,
            )
        )
        session.commit()
    return job_id


def delete_committed_job(job_id):
    with SessionLocal() as session:
        session.execute(delete(Job).where(Job.id == job_id))
        session.commit()


def run_race(insert_row):
    barrier = Barrier(2)
    outcomes = Queue()

    def worker(index):
        with SessionLocal() as session:
            try:
                session.add(insert_row(index))
                barrier.wait(timeout=5)
                session.commit()
            except IntegrityError:
                session.rollback()
                outcomes.put("integrity_error")
            except Exception as error:
                session.rollback()
                outcomes.put(f"unexpected:{type(error).__name__}")
            else:
                outcomes.put("committed")

    threads = [Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    return sorted(outcomes.get_nowait() for _ in range(2))


def test_concurrent_duplicate_category_has_one_database_winner():
    job_id = create_committed_race_crawl()
    try:
        outcomes = run_race(
            lambda _index: WikipediaCrawlFrontier(
                job_id=job_id,
                category_title="Category:Canonical duplicate",
                depth=1,
            )
        )
        assert outcomes == ["committed", "integrity_error"]
    finally:
        delete_committed_job(job_id)


def test_concurrent_duplicate_page_id_has_one_database_winner():
    job_id = create_committed_race_crawl()
    try:
        outcomes = run_race(
            lambda index: WikipediaCrawlPage(
                job_id=job_id,
                position=index,
                wikipedia_page_id=42,
                title=f"Concurrent page {index}",
                canonical_url=(
                    f"https://en.wikipedia.org/wiki/Concurrent_page_{index}"
                ),
            )
        )
        assert outcomes == ["committed", "integrity_error"]
    finally:
        delete_committed_job(job_id)


def test_checkpoint_replay_and_resume_are_durable_and_idempotent(db_session):
    job, _run, root = create_crawl(
        db_session,
        max_articles=3,
        max_depth=1,
    )
    db_session.commit()
    store = WikipediaCrawlStore(
        session_factory=session_factory_for(db_session)
    )
    continuation = {"cmcontinue": "page|next", "continue": "-||"}
    first_batch = category_batch(
        pages=((10, "First"), (11, "Second")),
        subcategories=((20, "Category:Child"),),
        continuation=continuation,
    )

    first_checkpoint = store.checkpoint_discovery(
        job.id,
        root.id,
        first_batch,
    )
    replay_checkpoint = store.checkpoint_discovery(
        job.id,
        root.id,
        first_batch,
    )
    final_checkpoint = store.checkpoint_discovery(
        job.id,
        root.id,
        category_batch(pages=((12, "Third"),)),
    )

    db_session.expire_all()
    pages = list(
        db_session.scalars(
            select(WikipediaCrawlPage)
            .where(WikipediaCrawlPage.job_id == job.id)
            .order_by(WikipediaCrawlPage.position)
        ).all()
    )
    frontiers = list(
        db_session.scalars(
            select(WikipediaCrawlFrontier)
            .where(WikipediaCrawlFrontier.job_id == job.id)
            .order_by(WikipediaCrawlFrontier.id)
        ).all()
    )
    run = db_session.get(WikipediaCrawlRun, job.id)

    assert first_checkpoint.discovered_count == 2
    assert replay_checkpoint.discovered_count == 2
    assert final_checkpoint.discovered_count == 3
    assert [page.position for page in pages] == [0, 1, 2]
    assert [page.wikipedia_page_id for page in pages] == [10, 11, 12]
    assert [frontier.category_title for frontier in frontiers] == [
        "Category:Root",
        "Category:Child",
    ]
    assert frontiers[0].continuation is None
    assert frontiers[0].status == "completed"
    assert run.discovery_complete is True


@pytest.mark.parametrize(
    ("subcategory_count", "expected_frontiers", "expected_limited"),
    [(99, 100, False), (100, 100, True)],
)
def test_depth_and_hundred_category_guards_persist_exactly(
    db_session,
    subcategory_count,
    expected_frontiers,
    expected_limited,
):
    job, _run, root = create_crawl(
        db_session,
        max_articles=500,
        max_depth=1,
    )
    db_session.commit()
    store = WikipediaCrawlStore(
        session_factory=session_factory_for(db_session)
    )
    subcategories = tuple(
        (1000 + index, f"Category:Child {index}")
        for index in range(subcategory_count)
    )

    checkpoint = store.checkpoint_discovery(
        job.id,
        root.id,
        category_batch(subcategories=subcategories),
    )

    db_session.expire_all()
    first_child = db_session.scalars(
        select(WikipediaCrawlFrontier)
        .where(
            WikipediaCrawlFrontier.job_id == job.id,
            WikipediaCrawlFrontier.depth == 1,
        )
        .order_by(WikipediaCrawlFrontier.id)
        .limit(1)
    ).one()
    store.checkpoint_discovery(
        job.id,
        first_child.id,
        category_batch(
            subcategories=((9999, "Category:Suppressed grandchild"),)
        ),
    )
    db_session.expire_all()
    frontier_count = db_session.scalar(
        select(func.count())
        .select_from(WikipediaCrawlFrontier)
        .where(WikipediaCrawlFrontier.job_id == job.id)
    )
    run = db_session.get(WikipediaCrawlRun, job.id)
    assert frontier_count == expected_frontiers
    assert checkpoint.category_limit_reached is expected_limited
    assert run.category_limit_reached is expected_limited
    assert db_session.scalar(
        select(func.count())
        .select_from(WikipediaCrawlFrontier)
        .where(
            WikipediaCrawlFrontier.job_id == job.id,
            WikipediaCrawlFrontier.category_title
            == "Category:Suppressed grandchild",
        )
    ) == 0
    assert all(
        frontier.depth <= 1
        for frontier in db_session.scalars(
            select(WikipediaCrawlFrontier).where(
                WikipediaCrawlFrontier.job_id == job.id
            )
        )
    )


class CommitFailingSession:
    def __init__(self, session):
        self.session = session

    def __getattr__(self, name):
        return getattr(self.session, name)

    def commit(self):
        raise RuntimeError("forced failure before commit")


def failing_session_factory(db_session):
    connection = db_session.connection()

    def factory():
        return CommitFailingSession(
            Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
            )
        )

    return factory


def test_checkpoint_failure_rolls_back_members_and_continuation(db_session):
    job, _run, root = create_crawl(db_session)
    db_session.commit()
    store = WikipediaCrawlStore(
        session_factory=failing_session_factory(db_session)
    )

    with pytest.raises(RuntimeError, match="forced failure before commit"):
        store.checkpoint_discovery(
            job.id,
            root.id,
            category_batch(
                pages=((10, "Not committed"),),
                continuation={"cmcontinue": "not-committed"},
            ),
        )

    db_session.expire_all()
    assert db_session.scalar(
        select(func.count())
        .select_from(WikipediaCrawlPage)
        .where(WikipediaCrawlPage.job_id == job.id)
    ) == 0
    persisted_root = db_session.get(WikipediaCrawlFrontier, root.id)
    assert persisted_root.continuation is None
    assert persisted_root.status == "pending"


def create_pending_page(db_session):
    job, _run, root = create_crawl(db_session, max_articles=1, max_depth=0)
    db_session.commit()
    store = WikipediaCrawlStore(
        session_factory=session_factory_for(db_session)
    )
    store.checkpoint_discovery(
        job.id,
        root.id,
        category_batch(pages=((10, "BM25"),)),
    )
    db_session.expire_all()
    page = db_session.scalars(
        select(WikipediaCrawlPage).where(
            WikipediaCrawlPage.job_id == job.id
        )
    ).one()
    return job, page, store


def test_fetch_staging_is_atomic_idempotent_and_cannot_be_overwritten(
    db_session,
):
    job, page, store = create_pending_page(db_session)
    payload = {
        "title": "BM25",
        "content": "BM25 ranking content from a fetched Wikipedia article.",
        "url": page.canonical_url,
    }

    store.stage_fetched_page(page.id, attempts=2, payload=payload)
    store.stage_fetched_page(page.id, attempts=3, payload=payload)
    store.fail_page(page.id, attempts=4, error="must_not_overwrite")

    db_session.expire_all()
    persisted = db_session.get(WikipediaCrawlPage, page.id)
    items = list(
        db_session.scalars(
            select(IngestionItem).where(IngestionItem.job_id == job.id)
        ).all()
    )
    assert persisted.fetch_status == FETCHED_FETCH_STATUS
    assert persisted.fetch_attempts == 2
    assert persisted.ingestion_item_id == items[0].id
    assert persisted.error is None
    assert len(items) == 1
    assert items[0].position == page.position
    assert items[0].payload == payload


def test_failed_page_stores_one_sanitized_terminal_error(db_session):
    _job, page, store = create_pending_page(db_session)

    store.fail_page(
        page.id,
        attempts=3,
        error=("private\nerror " + "x" * 400),
    )
    store.fail_page(page.id, attempts=4, error="must_not_overwrite")

    db_session.expire_all()
    persisted = db_session.get(WikipediaCrawlPage, page.id)
    assert persisted.fetch_status == FAILED_FETCH_STATUS
    assert persisted.fetch_attempts == 3
    assert len(persisted.error) == 300
    assert "\n" not in persisted.error


def test_failed_fetch_staging_rolls_back_item_and_page_transition(db_session):
    job, page, _store = create_pending_page(db_session)
    store = WikipediaCrawlStore(
        session_factory=failing_session_factory(db_session)
    )

    with pytest.raises(RuntimeError, match="forced failure before commit"):
        store.stage_fetched_page(
            page.id,
            attempts=1,
            payload={
                "title": "BM25",
                "content": "This staging transaction must roll back.",
                "url": page.canonical_url,
            },
        )

    db_session.expire_all()
    persisted = db_session.get(WikipediaCrawlPage, page.id)
    assert persisted.fetch_status == PENDING_FETCH_STATUS
    assert persisted.ingestion_item_id is None
    assert db_session.scalar(
        select(func.count())
        .select_from(IngestionItem)
        .where(IngestionItem.job_id == job.id)
    ) == 0


def test_counts_satisfy_all_crawl_outcome_equations(db_session):
    job, _run, root = create_crawl(db_session, max_articles=4, max_depth=0)
    db_session.commit()
    store = WikipediaCrawlStore(
        session_factory=session_factory_for(db_session)
    )
    store.checkpoint_discovery(
        job.id,
        root.id,
        category_batch(
            pages=(
                (10, "Imported"),
                (11, "Duplicate"),
                (12, "Invalid ingestion"),
                (13, "Fetch failure"),
            )
        ),
    )
    db_session.expire_all()
    pages = list(
        db_session.scalars(
            select(WikipediaCrawlPage)
            .where(WikipediaCrawlPage.job_id == job.id)
            .order_by(WikipediaCrawlPage.position)
        ).all()
    )
    for page in pages[:3]:
        store.stage_fetched_page(
            page.id,
            attempts=1,
            payload={
                "title": page.title,
                "content": f"Content for {page.title}",
                "url": page.canonical_url,
            },
        )
    store.fail_page(pages[3].id, attempts=3, error="wikipedia_not_found")

    db_session.expire_all()
    pages = list(
        db_session.scalars(
            select(WikipediaCrawlPage)
            .where(WikipediaCrawlPage.job_id == job.id)
            .order_by(WikipediaCrawlPage.position)
        ).all()
    )
    document = DocumentRepository(db_session).create(
        title="Imported",
        content="Imported document content.",
        url=f"https://example.com/{uuid4()}",
    )
    items = IngestionItemRepository(db_session)
    items.mark_imported(
        pages[0].ingestion_item_id,
        document_id=document.id,
    )
    items.mark_skipped(pages[1].ingestion_item_id, error="duplicate_url")
    items.mark_failed(pages[2].ingestion_item_id, error="invalid_payload")
    db_session.flush()

    counts = WikipediaCrawlRepository(db_session).counts(job.id)
    assert counts.discovered == 4
    assert counts.fetched == 3
    assert counts.imported == 1
    assert counts.skipped == 1
    assert counts.ingestion_failed == 1
    assert counts.fetch_failed == 1
    assert counts.fetched + counts.fetch_failed == counts.discovered
    assert (
        counts.imported + counts.skipped + counts.ingestion_failed
        == counts.fetched
    )
    assert counts.fetch_failed + counts.ingestion_failed == counts.failed
