from dataclasses import replace
import logging
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from app.models.job import (
    FAILURE_STATUS,
    PENDING_STATUS,
    STARTED_STATUS,
    SUCCESS_STATUS,
    WIKIPEDIA_CRAWL_JOB,
)
from app.services.job_tracker import JobTransitionError
from app.services.wikipedia_crawl_runner import (
    WikipediaCrawlCompletionError,
    WikipediaCrawlRunner,
)
from app.services.wikipedia_crawl_store import WikipediaCrawlStore
from app.services.wikipedia_types import CrawlCounts, CrawlRunSnapshot


JOB_ID = UUID("537949a4-2fea-4c51-bd22-9cbe5a842618")
INDEX_VERSION = f"redis-{JOB_ID}"


def crawl_counts(
    *,
    categories_visited=1,
    discovered=0,
    fetched=0,
    imported=0,
    skipped=0,
    fetch_failed=0,
    ingestion_failed=0,
):
    return CrawlCounts(
        categories_visited=categories_visited,
        discovered=discovered,
        fetched=fetched,
        imported=imported,
        skipped=skipped,
        fetch_failed=fetch_failed,
        ingestion_failed=ingestion_failed,
    )


SUCCESS_RESULT = {
    "root_category": "Category:Root",
    "max_articles": 4,
    "max_depth": 1,
    "categories_visited": 1,
    "category_limit_reached": False,
    "discovered_count": 4,
    "fetched_count": 3,
    "imported_count": 2,
    "duplicate_skipped_count": 1,
    "fetch_failed_count": 1,
    "ingestion_failed_count": 0,
    "failed_count": 1,
    "index_rebuilt": True,
    "index_version": INDEX_VERSION,
}


class FakeTracker:
    def __init__(self, job, events):
        self.job = job
        self.events = events
        self.claim_result = True
        self.claimed_with = None
        self.progress_updates = []
        self.success_with = None

    def get_job(self, _job_id):
        self.events.append("get_job")
        return self.job

    def claim(self, _job_id, **kwargs):
        self.events.append("claim")
        self.claimed_with = kwargs
        return self.claim_result

    def update_progress(self, _job_id, **kwargs):
        self.events.append(f"progress:{kwargs['progress_message']}")
        self.progress_updates.append(kwargs)

    def mark_success(self, _job_id, **kwargs):
        self.events.append("success")
        self.success_with = kwargs


class FakeCrawlStore:
    def __init__(self, run, counts, pending_ids, events):
        self.run_state = run
        self.counts_state = counts
        self.pending_ids = list(pending_ids)
        self.events = events
        self.get_run_calls = 0
        self.get_counts_calls = 0

    def get_run(self, _job_id):
        self.get_run_calls += 1
        return self.run_state

    def get_counts(self, _job_id):
        self.get_counts_calls += 1
        return self.counts_state

    def terminal_count(self, _job_id):
        return self.counts_state.terminal

    def list_pending_ingestion_ids(self, _job_id):
        self.events.append("list_pending_ingestion")
        return list(self.pending_ids)


class FakeDiscoveryPhase:
    def __init__(self, store, after_counts, events):
        self.store = store
        self.after_counts = after_counts
        self.events = events
        self.calls = []

    async def run(self, job_id):
        self.events.append("discovery")
        self.calls.append(job_id)
        self.store.run_state = replace(
            self.store.run_state,
            discovery_complete=True,
        )
        self.store.counts_state = self.after_counts
        return self.after_counts.discovered


class FakeFetchingPhase:
    def __init__(self, store, after_counts, progress_values, events):
        self.store = store
        self.after_counts = after_counts
        self.progress_values = list(progress_values)
        self.events = events
        self.calls = []

    async def run(self, job_id, *, progress_callback):
        self.events.append("fetching")
        self.calls.append(job_id)
        for current in self.progress_values:
            progress_callback(current)
        self.store.counts_state = self.after_counts


class FakeProcessor:
    def __init__(self, store, outcomes, events):
        self.store = store
        self.outcomes = list(outcomes)
        self.events = events
        self.processed_ids = []
        self.private_payload = "PRIVATE-INGESTION-PAYLOAD-731"

    def process(self, item_id):
        self.events.append(f"process:{item_id}")
        self.processed_ids.append(item_id)
        outcome = self.outcomes.pop(0)
        counts = self.store.counts_state
        if outcome == "imported":
            self.store.counts_state = replace(
                counts,
                imported=counts.imported + 1,
            )
        elif outcome == "skipped":
            self.store.counts_state = replace(
                counts,
                skipped=counts.skipped + 1,
            )
        elif outcome == "failed":
            self.store.counts_state = replace(
                counts,
                ingestion_failed=counts.ingestion_failed + 1,
            )
        else:
            raise AssertionError(f"unsupported fake outcome {outcome}")
        return SimpleNamespace(status=outcome)


class FakeClient:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        self.events.append("client_enter")
        return self

    async def __aexit__(self, *_exc_info):
        self.events.append("client_exit")


class FakeClientFactory:
    def __init__(self, client):
        self.client = client
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.client


class FakeRebuild:
    def __init__(self, events):
        self.events = events
        self.calls = []
        self.error = None

    def __call__(self, index_version):
        self.events.append("rebuild")
        self.calls.append(index_version)
        if self.error is not None:
            raise self.error
        return {"index_version": index_version, "document_count": 2}


class FakeSnapshotStore:
    def __init__(self, active_version="redis-existing"):
        self.active_version = active_version
        self.calls = 0

    def get_active_version(self):
        self.calls += 1
        return self.active_version


def build_fixture(
    *,
    job_status=PENDING_STATUS,
    job_type=WIKIPEDIA_CRAWL_JOB,
    stored_result=None,
    discovery_complete=False,
    category_limit_reached=False,
    discovered=4,
    after_fetch=None,
    pending_ids=(71, 72, 73),
    outcomes=("imported", "imported", "skipped"),
    fetch_progress=(0, 0, 0, 1),
    active_version="redis-existing",
):
    events = []
    job = SimpleNamespace(
        id=JOB_ID,
        job_type=job_type,
        status=job_status,
        result=stored_result,
    )
    tracker = FakeTracker(job, events)
    run = CrawlRunSnapshot(
        job_id=JOB_ID,
        root_category="Category:Root",
        max_articles=4,
        max_depth=1,
        discovery_complete=discovery_complete,
        category_limit_reached=category_limit_reached,
    )
    discovered_counts = crawl_counts(discovered=discovered)
    initial_counts = (
        discovered_counts if discovery_complete else crawl_counts()
    )
    store = FakeCrawlStore(run, initial_counts, pending_ids, events)
    discovery = FakeDiscoveryPhase(store, discovered_counts, events)
    fetched_counts = after_fetch or crawl_counts(
        discovered=discovered,
        fetched=3,
        fetch_failed=1,
    )
    fetching = FakeFetchingPhase(
        store,
        fetched_counts,
        fetch_progress,
        events,
    )
    processor = FakeProcessor(store, outcomes, events)
    client = FakeClient(events)
    client_factory = FakeClientFactory(client)
    rebuild = FakeRebuild(events)
    snapshot_store = FakeSnapshotStore(active_version)
    runner = WikipediaCrawlRunner(
        tracker=tracker,
        store=store,
        processor=processor,
        client_factory=client_factory,
        discovery_factory=lambda _store, _client: discovery,
        fetching_factory=lambda _store, _client: fetching,
        rebuild=rebuild,
        snapshot_store=snapshot_store,
    )
    return SimpleNamespace(
        runner=runner,
        tracker=tracker,
        store=store,
        discovery=discovery,
        fetching=fetching,
        processor=processor,
        client_factory=client_factory,
        rebuild=rebuild,
        snapshot_store=snapshot_store,
        events=events,
    )


def test_runner_claims_discovers_fetches_ingests_rebuilds_and_succeeds():
    fixture = build_fixture()

    result = fixture.runner.run(JOB_ID)

    assert fixture.tracker.claimed_with == {
        "progress_current": 0,
        "progress_total": None,
        "progress_message": "Discovering Wikipedia articles",
    }
    assert fixture.discovery.calls == [JOB_ID]
    assert fixture.fetching.calls == [JOB_ID]
    assert fixture.processor.processed_ids == [71, 72, 73]
    assert fixture.rebuild.calls == [INDEX_VERSION]
    assert result == SUCCESS_RESULT
    assert fixture.tracker.success_with == {
        "result": SUCCESS_RESULT,
        "progress_total": 5,
        "progress_message": "Wikipedia crawl completed",
    }
    assert fixture.events.index("client_exit") < fixture.events.index(
        "process:71"
    )


def test_progress_uses_durable_counts_and_exact_phase_messages():
    fixture = build_fixture()

    fixture.runner.run(JOB_ID)

    updates = fixture.tracker.progress_updates
    assert [update["progress_message"] for update in updates] == [
        "Fetching Wikipedia articles",
        "Fetching Wikipedia articles",
        "Fetching Wikipedia articles",
        "Fetching Wikipedia articles",
        "Fetching Wikipedia articles",
        "Ingesting Wikipedia articles",
        "Processed article 2 of 4",
        "Processed article 3 of 4",
        "Processed article 4 of 4",
        "Rebuilding search index",
    ]
    assert [update["progress_current"] for update in updates] == [
        0,
        0,
        0,
        0,
        1,
        1,
        2,
        3,
        4,
        4,
    ]
    assert {update["progress_total"] for update in updates} == {5}


def test_started_job_resumes_without_second_claim():
    fixture = build_fixture(
        job_status=STARTED_STATUS,
        discovery_complete=True,
    )

    result = fixture.runner.run(JOB_ID)

    assert result == SUCCESS_RESULT
    assert fixture.tracker.claimed_with is None
    assert fixture.client_factory.calls == 1


def test_completed_discovery_skips_action_api_phase():
    fixture = build_fixture(discovery_complete=True)

    fixture.runner.run(JOB_ID)

    assert fixture.discovery.calls == []
    assert fixture.fetching.calls == [JOB_ID]


def test_successful_redelivery_returns_stored_result_without_http_client():
    stored = {"stored": "result"}
    fixture = build_fixture(
        job_status=SUCCESS_STATUS,
        stored_result=stored,
    )

    result = fixture.runner.run(JOB_ID)

    assert result == stored
    assert result is not stored
    assert fixture.client_factory.calls == 0
    assert fixture.store.get_run_calls == 0


@pytest.mark.parametrize(
    ("job_status", "job_type", "missing"),
    [
        (PENDING_STATUS, WIKIPEDIA_CRAWL_JOB, True),
        (PENDING_STATUS, "bulk_document_ingestion", False),
        (FAILURE_STATUS, WIKIPEDIA_CRAWL_JOB, False),
    ],
)
def test_missing_wrong_type_and_failed_jobs_are_rejected_without_work(
    job_status,
    job_type,
    missing,
):
    fixture = build_fixture(job_status=job_status, job_type=job_type)
    if missing:
        fixture.tracker.job = None

    with pytest.raises(JobTransitionError):
        fixture.runner.run(JOB_ID)

    assert fixture.client_factory.calls == 0
    assert fixture.store.get_run_calls == 0


def test_unclaimable_pending_job_is_rejected():
    fixture = build_fixture()
    fixture.tracker.claim_result = False

    with pytest.raises(JobTransitionError):
        fixture.runner.run(JOB_ID)

    assert fixture.client_factory.calls == 0
    assert fixture.store.get_run_calls == 0


def test_zero_discovered_pages_raise_completion_error_before_fetching():
    fixture = build_fixture(discovered=0, pending_ids=(), outcomes=())

    with pytest.raises(WikipediaCrawlCompletionError) as caught:
        fixture.runner.run(JOB_ID)

    assert str(caught.value) == "wikipedia_crawl_no_articles"
    assert fixture.fetching.calls == []
    assert fixture.rebuild.calls == []
    assert fixture.tracker.success_with is None


def test_every_page_fetch_failed_raises_before_ingestion_or_rebuild():
    fixture = build_fixture(
        after_fetch=crawl_counts(discovered=4, fetch_failed=4),
        pending_ids=(),
        outcomes=(),
        fetch_progress=(1, 2, 3, 4),
    )

    with pytest.raises(WikipediaCrawlCompletionError) as caught:
        fixture.runner.run(JOB_ID)

    assert str(caught.value) == "wikipedia_crawl_no_fetched_articles"
    assert fixture.processor.processed_ids == []
    assert fixture.rebuild.calls == []


def test_all_fetched_ingestion_failures_raise_completion_error():
    fixture = build_fixture(outcomes=("failed", "failed", "failed"))

    with pytest.raises(WikipediaCrawlCompletionError) as caught:
        fixture.runner.run(JOB_ID)

    assert str(caught.value) == "wikipedia_crawl_no_usable_documents"
    assert fixture.processor.processed_ids == [71, 72, 73]
    assert fixture.rebuild.calls == []


def test_inconsistent_fetch_counts_are_rejected_as_durable_state_error():
    fixture = build_fixture(
        after_fetch=crawl_counts(
            discovered=4,
            fetched=2,
            fetch_failed=1,
        ),
        pending_ids=(),
        outcomes=(),
    )

    with pytest.raises(JobTransitionError, match="fetch counts"):
        fixture.runner.run(JOB_ID)

    assert fixture.processor.processed_ids == []
    assert fixture.rebuild.calls == []


def test_inconsistent_ingestion_counts_are_rejected_before_publication():
    fixture = build_fixture(
        pending_ids=(71, 72),
        outcomes=("imported", "skipped"),
    )

    with pytest.raises(JobTransitionError, match="ingestion counts"):
        fixture.runner.run(JOB_ID)

    assert fixture.processor.processed_ids == [71, 72]
    assert fixture.rebuild.calls == []


def test_duplicate_only_success_reuses_active_version_without_rebuild():
    fixture = build_fixture(
        discovered=2,
        after_fetch=crawl_counts(discovered=2, fetched=2),
        pending_ids=(71, 72),
        outcomes=("skipped", "skipped"),
        fetch_progress=(0, 0),
        active_version="redis-current",
    )

    result = fixture.runner.run(JOB_ID)

    assert fixture.rebuild.calls == []
    assert fixture.snapshot_store.calls == 1
    assert result["index_rebuilt"] is False
    assert result["index_version"] == "redis-current"
    assert fixture.tracker.progress_updates[-1] == {
        "progress_current": 2,
        "progress_total": 3,
        "progress_message": "No index changes required",
    }


def test_one_import_triggers_exactly_one_rebuild_despite_failures():
    fixture = build_fixture(outcomes=("imported", "failed", "failed"))

    result = fixture.runner.run(JOB_ID)

    assert fixture.rebuild.calls == [INDEX_VERSION]
    assert result["imported_count"] == 1
    assert result["ingestion_failed_count"] == 2
    assert result["failed_count"] == 3


def test_rebuild_failure_propagates_without_successful_completion():
    fixture = build_fixture()
    fixture.rebuild.error = RuntimeError("redis publication unavailable")

    with pytest.raises(RuntimeError, match="redis publication unavailable"):
        fixture.runner.run(JOB_ID)

    assert fixture.rebuild.calls == [INDEX_VERSION]
    assert fixture.tracker.success_with is None


def test_final_result_uses_fresh_state_and_satisfies_count_equations():
    fixture = build_fixture(category_limit_reached=True)

    result = fixture.runner.run(JOB_ID)

    assert result["category_limit_reached"] is True
    assert result["fetched_count"] + result["fetch_failed_count"] == result[
        "discovered_count"
    ]
    assert (
        result["imported_count"]
        + result["duplicate_skipped_count"]
        + result["ingestion_failed_count"]
        == result["fetched_count"]
    )
    assert (
        result["fetch_failed_count"] + result["ingestion_failed_count"]
        == result["failed_count"]
    )
    assert fixture.store.get_run_calls >= 2


def test_structured_phase_logs_do_not_include_content_or_payloads(caplog):
    fixture = build_fixture()
    private_html = "PRIVATE-ARTICLE-HTML-947"
    fixture.processor.private_html = private_html
    caplog.set_level(
        logging.INFO,
        logger="app.services.wikipedia_crawl_runner",
    )

    fixture.runner.run(JOB_ID)

    records = [
        record
        for record in caplog.records
        if record.name == "app.services.wikipedia_crawl_runner"
    ]
    assert "wikipedia_crawl_phase" in {
        record.getMessage() for record in records
    }
    assert "wikipedia_crawl_completed" in {
        record.getMessage() for record in records
    }
    for record in records:
        assert record.job_id == str(JOB_ID)
        assert isinstance(record.phase, str)
        assert isinstance(record.outcome, str)
        assert isinstance(record.discovered_count, int)
        assert isinstance(record.fetched_count, int)
        assert isinstance(record.terminal_count, int)
    serialized = "\n".join(
        f"{record.getMessage()} {record.__dict__!r}" for record in records
    )
    assert fixture.processor.private_payload not in serialized
    assert private_html not in serialized


def test_store_lists_plain_pending_ingestion_ids_and_closes_session():
    session = Mock()
    repository = Mock()
    repository.get_run.return_value = CrawlRunSnapshot(
        job_id=JOB_ID,
        root_category="Category:Root",
        max_articles=4,
        max_depth=1,
        discovery_complete=True,
        category_limit_reached=False,
    )
    repository.list_pending_ingestion_ids.return_value = [71, 72]
    store = WikipediaCrawlStore(
        session_factory=lambda: session,
        repository_factory=lambda _session: repository,
        ingestion_repository_factory=lambda _session: Mock(),
        max_categories=100,
    )

    item_ids = store.list_pending_ingestion_ids(JOB_ID)

    assert item_ids == [71, 72]
    assert all(type(item_id) is int for item_id in item_ids)
    repository.list_pending_ingestion_ids.assert_called_once_with(JOB_ID)
    session.close.assert_called_once_with()
