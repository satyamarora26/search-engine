from types import SimpleNamespace
from uuid import UUID

import pytest

from app.models.job import PENDING_STATUS, RSS_CRAWL_JOB, SEARCH_INDEX_RESOURCE
from app.schemas.rss_crawls import RssCrawlRequest
from app.services.crawl_types import CrawlItemView
from app.services.jobs import IndexJobConflictError
from app.services.rss_crawls import RssCrawlNotFoundError, RssCrawlService

JOB_ID = UUID("dd7fc5c3-1be5-4771-8db4-a49eb6a32e2b")


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeJobs:
    def __init__(self):
        self.active = None
        self.job = None
        self.created = None

    def get_active_by_resource(self, resource_key):
        assert resource_key == SEARCH_INDEX_RESOURCE
        return self.active

    def create_pending(self, job_id, **values):
        self.created = {"job_id": job_id, **values}
        self.job = SimpleNamespace(id=job_id, status=PENDING_STATUS, **values)
        return self.job

    def get(self, job_id):
        return self.job if self.job and self.job.id == job_id else None


class FakeCrawls:
    def __init__(self):
        self.run = None
        self.frontiers = []

    def create_run(self, job_id, **values):
        self.run = {"job_id": job_id, **values}

    def add_frontier(self, job_id, **values):
        self.frontiers.append({"job_id": job_id, **values})

    def count_item_views(self, _job_id):
        return 0

    def list_item_views(self, _job_id, *, limit, offset):
        assert (limit, offset) == (10, 0)
        return []


class FakeTask:
    def __init__(self):
        self.calls = []

    def apply_async(self, *, args, task_id):
        self.calls.append((args, task_id))


def fixture():
    session = FakeSession()
    jobs = FakeJobs()
    crawls = FakeCrawls()
    task = FakeTask()
    service = RssCrawlService(
        session,
        task,
        job_id_factory=lambda: JOB_ID,
        job_repository=jobs,
        crawl_repository=crawls,
    )
    return service, session, jobs, crawls, task


def test_enqueue_creates_rss_job_and_feed_frontier():
    service, session, jobs, crawls, task = fixture()

    service.enqueue_crawl(
        RssCrawlRequest(feed_url="https://example.com/feed.xml?format=rss", max_articles=7)
    )

    assert jobs.created["job_type"] == RSS_CRAWL_JOB
    assert crawls.run == {
        "job_id": JOB_ID,
        "source_key": "rss",
        "seed_url": "https://example.com/feed.xml?format=rss",
        "max_articles": 7,
        "max_depth": 0,
    }
    assert crawls.frontiers == [{
        "job_id": JOB_ID,
        "locator": "https://example.com/feed.xml?format=rss",
        "depth": 0,
    }]
    assert task.calls == [([str(JOB_ID)], str(JOB_ID))]
    assert session.commits == 1


def test_active_resource_rejects_rss_crawl():
    service, _session, jobs, crawls, task = fixture()
    jobs.active = SimpleNamespace(
        id=UUID("4f6dca6c-bbd3-48d0-8ab1-8141e2f2a30d"),
        resource_key=SEARCH_INDEX_RESOURCE,
    )

    with pytest.raises(IndexJobConflictError):
        service.enqueue_crawl(RssCrawlRequest(feed_url="https://example.com/feed.xml"))

    assert crawls.run is None
    assert task.calls == []


def test_list_items_rejects_wrong_job_type():
    service, _session, jobs, _crawls, _task = fixture()
    jobs.job = SimpleNamespace(id=JOB_ID, job_type="medium_crawl")

    with pytest.raises(RssCrawlNotFoundError):
        service.list_items(JOB_ID, limit=10, offset=0)
