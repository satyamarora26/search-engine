from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.models.job import (
    FAILURE_STATUS,
    MEDIUM_CRAWL_JOB,
    PENDING_STATUS,
    STARTED_STATUS,
    SUCCESS_STATUS,
)
from app.services.crawl_runner import CrawlCompletionError, CrawlRunner
from app.services.crawl_types import (
    CrawlCounts,
    CrawlItemSnapshot,
    CrawlRunSnapshot,
    DiscoveredItem,
    DiscoveryBatch,
    NormalizedDocument,
    NormalizedSeed,
    RawPage,
)
from app.services.job_tracker import JobTransitionError

JOB_ID = UUID("537949a4-2fea-4c51-bd22-9cbe5a842618")
INDEX_VERSION = f"redis-{JOB_ID}"


class FakeTracker:
    def __init__(self, job, events):
        self.job = job
        self.events = events
        self.claimed_with = None
        self.progress_updates = []
        self.success_with = None

    def get_job(self, _job_id):
        self.events.append("get_job")
        return self.job

    def claim(self, _job_id, **kwargs):
        self.events.append("claim")
        self.claimed_with = kwargs
        return True

    def update_progress(self, _job_id, **kwargs):
        self.events.append(f"progress:{kwargs['progress_message']}")
        self.progress_updates.append(kwargs)

    def mark_success(self, _job_id, **kwargs):
        self.events.append("success")
        self.success_with = kwargs


class FakeStore:
    def __init__(self, run, events):
        self.run_state = run
        self.counts_state = CrawlCounts(0, 0, 0, 0, 0, 0)
        self.items = []
        self.events = events

    def get_run(self, _job_id):
        return self.run_state

    def get_counts(self, _job_id):
        return self.counts_state

    def checkpoint_discovery(self, _job_id, batch):
        self.events.append("discovery")
        self.run_state = replace(self.run_state, discovery_complete=True)
        self.counts_state = replace(self.counts_state, discovered=len(batch.items))

    def list_pending_items(self, _job_id):
        self.events.append("pending_items")
        return list(self.items)

    def stage_fetched_document(self, item_id, document, *, attempts):
        self.events.append(f"stage:{item_id}")
        self.counts_state = replace(
            self.counts_state,
            fetched=self.counts_state.fetched + 1,
        )

    def fail_item(self, item_id, *, attempts, error):
        self.events.append(f"fail:{item_id}:{error}")
        self.counts_state = replace(
            self.counts_state,
            fetch_failed=self.counts_state.fetch_failed + 1,
        )

    def list_pending_ingestion_ids(self, _job_id):
        self.events.append("pending_ingestion")
        return [91, 92, 93]


class FakeAdapter:
    source_key = "medium"

    def __init__(self, events):
        self.events = events
        self.documents = {
            "https://medium.com/towards-data-science/one": NormalizedDocument(
                "One", "https://medium.com/towards-data-science/one", "one body"
            ),
            "https://medium.com/towards-data-science/two": NormalizedDocument(
                "Two", "https://medium.com/towards-data-science/two", "two body"
            ),
        }

    def validate_seed(self, seed_url):
        return NormalizedSeed("medium", seed_url, "https://medium.com", "/towards-data-science")

    async def __aenter__(self):
        self.events.append("adapter_enter")
        return self

    async def __aexit__(self, *_exc_info):
        self.events.append("adapter_exit")

    async def discover(self, _seed, _limits):
        self.events.append("adapter_discover")
        yield DiscoveryBatch(
            items=tuple(
                DiscoveredItem(
                    source_item_id=url.rsplit("/", 1)[-1],
                    title=url.rsplit("/", 1)[-1].title(),
                    discovered_url=url,
                    canonical_url=url,
                )
                for url in self.documents
            ),
            frontier_locator="https://medium.com/feed/towards-data-science",
            continuation=None,
            complete=True,
        )

    async def fetch(self, item):
        self.events.append(f"fetch:{item.canonical_url}")
        return RawPage(item.canonical_url, 200, "text/html", b"body", 1)

    def parse(self, raw_page):
        return self.documents[raw_page.url]


class FakeProcessor:
    def __init__(self, store, events):
        self.store = store
        self.events = events
        self.processed_ids = []

    def process(self, item_id):
        self.events.append(f"process:{item_id}")
        self.processed_ids.append(item_id)
        self.store.counts_state = replace(
            self.store.counts_state,
            imported=self.store.counts_state.imported + 1,
        )


class FakeRebuild:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def __call__(self, index_version):
        self.events.append("rebuild")
        self.calls.append(index_version)
        return {"index_version": index_version}


class FakeSnapshotStore:
    def get_active_version(self):
        return "redis-existing"


def build_fixture(*, status=PENDING_STATUS, result=None):
    events = []
    job = SimpleNamespace(
        id=JOB_ID,
        job_type=MEDIUM_CRAWL_JOB,
        status=status,
        result=result,
    )
    tracker = FakeTracker(job, events)
    run = CrawlRunSnapshot(
        job_id=JOB_ID,
        source_key="medium",
        seed_url="https://medium.com/towards-data-science",
        max_articles=2,
        max_depth=0,
        discovery_complete=status == STARTED_STATUS,
        limit_reached=False,
    )
    store = FakeStore(run, events)
    if status == STARTED_STATUS:
        store.counts_state = CrawlCounts(2, 0, 0, 0, 0, 0)
    store.items = [
        CrawlItemSnapshot(
            id=71,
            position=0,
            discovered_item=DiscoveredItem(
                "one",
                "One",
                "https://medium.com/towards-data-science/one",
                "https://medium.com/towards-data-science/one",
            ),
        ),
        CrawlItemSnapshot(
            id=72,
            position=1,
            discovered_item=DiscoveredItem(
                "two",
                "Two",
                "https://medium.com/towards-data-science/two",
                "https://medium.com/towards-data-science/two",
            ),
        ),
    ]
    adapter = FakeAdapter(events)
    processor = FakeProcessor(store, events)
    rebuild = FakeRebuild(events)
    runner = CrawlRunner(
        tracker=tracker,
        store=store,
        processor=processor,
        adapter_resolver=lambda _source: adapter,
        rebuild=rebuild,
        snapshot_store=FakeSnapshotStore(),
    )
    return SimpleNamespace(
        runner=runner,
        tracker=tracker,
        store=store,
        adapter=adapter,
        processor=processor,
        rebuild=rebuild,
        events=events,
    )


def test_runner_discovers_fetches_ingests_rebuilds_and_succeeds():
    fixture = build_fixture()

    result = fixture.runner.run(JOB_ID)

    assert fixture.tracker.claimed_with["progress_message"] == "Discovering Medium articles"
    assert fixture.processor.processed_ids == [91, 92, 93]
    assert fixture.rebuild.calls == [f"redis-{JOB_ID}"]
    assert result["source"] == "medium"
    assert result["discovered_count"] == 2
    assert result["fetched_count"] == 2
    assert result["imported_count"] == 3
    assert result["index_rebuilt"] is True
    assert fixture.tracker.success_with["progress_message"] == "Medium crawl completed"


def test_started_job_resumes_without_claiming_or_discovery():
    fixture = build_fixture(status=STARTED_STATUS)

    fixture.runner.run(JOB_ID)

    assert "claim" not in fixture.events
    assert "adapter_discover" not in fixture.events


def test_successful_redelivery_returns_stored_result_without_work():
    result = {"source": "medium", "index_version": INDEX_VERSION}
    fixture = build_fixture(status=SUCCESS_STATUS, result=result)

    assert fixture.runner.run(JOB_ID) == result
    assert fixture.events == ["get_job"]
    assert fixture.rebuild.calls == []


def test_failed_job_and_wrong_job_are_rejected():
    fixture = build_fixture(status=FAILURE_STATUS)

    with pytest.raises(JobTransitionError, match="already failed"):
        fixture.runner.run(JOB_ID)

    wrong = build_fixture()
    wrong.tracker.job.job_type = "wikipedia_crawl"
    with pytest.raises(JobTransitionError, match="missing or invalid"):
        wrong.runner.run(JOB_ID)


def test_no_discovered_articles_is_a_terminal_completion_error():
    fixture = build_fixture()
    fixture.adapter.discover = lambda _seed, _limits: _empty_batches()

    with pytest.raises(CrawlCompletionError, match="medium_crawl_no_articles"):
        fixture.runner.run(JOB_ID)


async def _empty_batches():
    if False:
        yield None
