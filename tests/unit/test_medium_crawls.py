from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.job import (
    MEDIUM_CRAWL_JOB,
    PENDING_STATUS,
    SEARCH_INDEX_REBUILD_JOB,
    SEARCH_INDEX_RESOURCE,
)
from app.schemas.medium_crawls import MediumCrawlRequest
from app.services.jobs import IndexJobConflictError, JobEnqueueError, JobStorageError
from app.services.medium_crawls import (
    MediumCrawlNotFoundError,
    MediumCrawlService,
)
from app.services.crawl_types import CrawlItemView

JOB_ID = UUID("0ea30c3d-273f-44cc-a43f-489c2ece940d")
ACTIVE_JOB_ID = UUID("3d19cc7a-4895-42f6-954c-fd562dadc75a")
DEFAULT_REQUEST = MediumCrawlRequest(
    publication_url="https://medium.com/towards-data-science"
)


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeJobRepository:
    def __init__(self):
        self.active_results = [None]
        self.create_error = None
        self.failure_error = None
        self.job = None
        self.created_with = None
        self.failed_with = None

    def get_active_by_resource(self, resource_key):
        assert resource_key == SEARCH_INDEX_RESOURCE
        if len(self.active_results) > 1:
            return self.active_results.pop(0)
        return self.active_results[0]

    def create_pending(self, job_id, **values):
        self.created_with = {"job_id": job_id, **values}
        if self.create_error:
            raise self.create_error
        self.job = SimpleNamespace(id=job_id, status=PENDING_STATUS, **values)
        return self.job

    def mark_pending_failure(self, job_id, *, error):
        self.failed_with = {"job_id": job_id, "error": error}
        if self.failure_error:
            raise self.failure_error
        return self.job

    def get(self, job_id):
        return self.job if self.job is not None and self.job.id == job_id else None


class FakeCrawlRepository:
    def __init__(self):
        self.create_error = None
        self.count_error = None
        self.run_created_with = None
        self.frontiers_created_with = []
        self.total = 0
        self.listed = []
        self.listed_with = None

    def create_run(self, job_id, **values):
        self.run_created_with = {"job_id": job_id, **values}
        if self.create_error:
            raise self.create_error
        return SimpleNamespace(job_id=job_id, **values)

    def add_frontier(self, job_id, **values):
        self.frontiers_created_with.append({"job_id": job_id, **values})
        return SimpleNamespace(job_id=job_id, **values)

    def count_item_views(self, job_id):
        if self.count_error:
            raise self.count_error
        return self.total

    def list_item_views(self, job_id, *, limit, offset):
        self.listed_with = {"job_id": job_id, "limit": limit, "offset": offset}
        return self.listed


class FakeTask:
    def __init__(self, session):
        self.session = session
        self.error = None
        self.calls = []
        self.commits_when_called = []

    def apply_async(self, *, args, task_id):
        self.commits_when_called.append(self.session.commits)
        self.calls.append({"args": args, "task_id": task_id})
        if self.error:
            raise self.error


def active_job(job_type=SEARCH_INDEX_REBUILD_JOB):
    return SimpleNamespace(
        id=ACTIVE_JOB_ID,
        job_type=job_type,
        resource_key=SEARCH_INDEX_RESOURCE,
        status=PENDING_STATUS,
    )


def service_fixture():
    session = FakeSession()
    jobs = FakeJobRepository()
    crawls = FakeCrawlRepository()
    task = FakeTask(session)
    service = MediumCrawlService(
        session,
        task,
        job_id_factory=lambda: JOB_ID,
        job_repository=jobs,
        crawl_repository=crawls,
    )
    return service, session, jobs, crawls, task


def test_enqueue_creates_medium_job_run_and_discovery_frontiers():
    service, session, jobs, crawls, task = service_fixture()

    job = service.enqueue_crawl(
        MediumCrawlRequest(
            publication_url="https://medium.com/towards-data-science/",
            max_articles=25,
        )
    )

    assert jobs.created_with == {
        "job_id": JOB_ID,
        "job_type": MEDIUM_CRAWL_JOB,
        "resource_key": SEARCH_INDEX_RESOURCE,
        "progress_total": None,
        "progress_message": "Waiting for worker",
    }
    assert crawls.run_created_with == {
        "job_id": JOB_ID,
        "source_key": "medium",
        "seed_url": "https://medium.com/towards-data-science",
        "max_articles": 25,
        "max_depth": 0,
    }
    assert crawls.frontiers_created_with == [
        {
            "job_id": JOB_ID,
            "locator": "https://medium.com/feed/towards-data-science",
            "depth": 0,
        },
        {
            "job_id": JOB_ID,
            "locator": "https://medium.com/sitemap.xml",
            "depth": 0,
        },
    ]
    assert session.commits == 1
    assert task.calls == [{"args": [str(JOB_ID)], "task_id": str(JOB_ID)}]
    assert task.commits_when_called == [1]
    assert job.id == JOB_ID


def test_active_resource_rejects_medium_crawl_before_writes():
    service, session, jobs, crawls, task = service_fixture()
    jobs.active_results = [active_job()]

    with pytest.raises(IndexJobConflictError):
        service.enqueue_crawl(DEFAULT_REQUEST)

    assert jobs.created_with is None
    assert crawls.run_created_with is None
    assert task.calls == []
    assert session.commits == 0


def test_unique_resource_race_reports_winning_job():
    service, session, jobs, crawls, task = service_fixture()
    winner = active_job(job_type=MEDIUM_CRAWL_JOB)
    jobs.active_results = [None, winner]
    jobs.create_error = IntegrityError("INSERT", {}, Exception())

    with pytest.raises(IndexJobConflictError) as caught:
        service.enqueue_crawl(DEFAULT_REQUEST)

    assert caught.value.active_job is winner
    assert session.rollbacks == 1
    assert crawls.run_created_with is None
    assert task.calls == []


def test_database_and_broker_failures_are_safe_and_transactional():
    service, session, _jobs, crawls, task = service_fixture()
    crawls.create_error = SQLAlchemyError("database hostname leaked")

    with pytest.raises(JobStorageError, match="Job storage unavailable"):
        service.enqueue_crawl(DEFAULT_REQUEST)
    assert session.rollbacks == 1

    service, session, jobs, _crawls, task = service_fixture()
    task.error = ConnectionError("redis password leaked")
    with pytest.raises(JobEnqueueError, match="Could not enqueue"):
        service.enqueue_crawl(DEFAULT_REQUEST)
    assert jobs.failed_with["error"] == "Could not enqueue background job."
    assert session.commits == 2


def test_list_items_returns_page_and_rejects_unknown_jobs():
    service, _session, jobs, crawls, _task = service_fixture()
    jobs.job = SimpleNamespace(id=JOB_ID, job_type=MEDIUM_CRAWL_JOB)
    crawls.total = 1
    crawls.listed = [
        CrawlItemView(
            0,
            "article-1",
            "Article",
            "https://medium.com/towards-data-science/article-1",
            "fetched",
            "imported",
            81,
            None,
        )
    ]

    total, items = service.list_items(JOB_ID, limit=10, offset=0)

    assert total == 1
    assert items[0].source_item_id == "article-1"
    assert crawls.listed_with == {"job_id": JOB_ID, "limit": 10, "offset": 0}

    jobs.job = SimpleNamespace(id=JOB_ID, job_type=SEARCH_INDEX_REBUILD_JOB)
    with pytest.raises(MediumCrawlNotFoundError):
        service.list_items(JOB_ID, limit=10, offset=0)
