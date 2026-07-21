from types import SimpleNamespace
from uuid import UUID

import pytest

from app.models.job import (
    BULK_DOCUMENT_INGESTION_JOB,
    FAILURE_STATUS,
    PENDING_STATUS,
    SEARCH_INDEX_REBUILD_JOB,
    STARTED_STATUS,
    SUCCESS_STATUS,
)
from app.repositories.ingestion_items import IngestionCounts
from app.services.bulk_ingestion_runner import (
    BulkIngestionRunner,
    IngestionItemStore,
)
from app.services.job_tracker import JobTransitionError

JOB_ID = UUID("d46c43aa-2cd6-47f4-a653-c3274c8413f9")
SUCCESS_RESULT = {
    "received_count": 3,
    "imported_count": 1,
    "skipped_count": 1,
    "failed_count": 1,
    "index_rebuilt": True,
    "index_version": f"redis-{JOB_ID}",
}


class FakeTracker:
    def __init__(self) -> None:
        self.job = SimpleNamespace(
            id=JOB_ID,
            job_type=BULK_DOCUMENT_INGESTION_JOB,
            status=PENDING_STATUS,
            progress_total=4,
            result=None,
        )
        self.claimed = True
        self.calls = []

    def get_job(self, job_id: UUID):
        self.calls.append(("get", job_id))
        return self.job

    def claim(self, job_id: UUID, **values) -> bool:
        self.calls.append(("claim", job_id, values))
        return self.claimed

    def update_progress(self, job_id: UUID, **values) -> None:
        self.calls.append(("progress", job_id, values))

    def mark_success(
        self,
        job_id: UUID,
        *,
        result,
        progress_total: int,
        progress_message: str,
    ) -> None:
        self.calls.append(
            (
                "success",
                job_id,
                result,
                progress_total,
                progress_message,
            )
        )


class FakeItemStore:
    def __init__(self) -> None:
        self.pending_ids = [10, 11, 12]
        self.terminal_count = 0
        self.count_values = IngestionCounts(
            received=3,
            imported=1,
            skipped=1,
            failed=1,
        )
        self.calls = []

    def list_pending_ids(self, job_id: UUID) -> list[int]:
        self.calls.append(("pending", job_id))
        return self.pending_ids

    def count_terminal(self, job_id: UUID) -> int:
        self.calls.append(("terminal", job_id))
        return self.terminal_count

    def counts(self, job_id: UUID) -> IngestionCounts:
        self.calls.append(("counts", job_id))
        return self.count_values


class FakeProcessor:
    def __init__(self) -> None:
        self.processed_ids = []
        self.error = None

    def process(self, item_id: int) -> None:
        self.processed_ids.append(item_id)
        if self.error is not None:
            raise self.error


class FakeRebuild:
    def __init__(self) -> None:
        self.calls = []
        self.error = None

    def __call__(self, index_version: str):
        self.calls.append({"index_version": index_version})
        if self.error is not None:
            raise self.error
        return {"index_version": index_version, "document_count": 1}


class FakeSnapshotStore:
    def __init__(self) -> None:
        self.active_version = "redis-existing"
        self.calls = 0

    def get_active_version(self) -> str | None:
        self.calls += 1
        return self.active_version


def runner_fixture():
    tracker = FakeTracker()
    items = FakeItemStore()
    processor = FakeProcessor()
    rebuild = FakeRebuild()
    snapshot_store = FakeSnapshotStore()
    runner = BulkIngestionRunner(
        tracker=tracker,
        item_store=items,
        processor=processor,
        rebuild=rebuild,
        snapshot_store=snapshot_store,
    )
    return runner, tracker, items, processor, rebuild, snapshot_store


def test_runner_claims_processes_pending_items_rebuilds_once_and_succeeds():
    runner, tracker, _, processor, rebuild, snapshot_store = runner_fixture()

    result = runner.run(JOB_ID)

    assert processor.processed_ids == [10, 11, 12]
    assert rebuild.calls == [{"index_version": f"redis-{JOB_ID}"}]
    assert snapshot_store.calls == 0
    assert result == SUCCESS_RESULT
    assert tracker.calls[-1] == (
        "success",
        JOB_ID,
        result,
        4,
        "Bulk ingestion completed",
    )


def test_runner_records_progress_after_each_processed_item():
    runner, tracker, _, _, _, _ = runner_fixture()

    runner.run(JOB_ID)

    item_progress = [
        call[2]
        for call in tracker.calls
        if call[0] == "progress"
        and call[2]["progress_message"].startswith("Processed document")
    ]
    assert item_progress == [
        {
            "progress_current": 1,
            "progress_total": 4,
            "progress_message": "Processed document 1 of 3",
        },
        {
            "progress_current": 2,
            "progress_total": 4,
            "progress_message": "Processed document 2 of 3",
        },
        {
            "progress_current": 3,
            "progress_total": 4,
            "progress_message": "Processed document 3 of 3",
        },
    ]


def test_runner_skips_rebuild_when_nothing_was_imported():
    runner, _, items, _, rebuild, snapshot_store = runner_fixture()
    items.count_values = IngestionCounts(
        received=3,
        imported=0,
        skipped=2,
        failed=1,
    )
    snapshot_store.active_version = "redis-existing"

    result = runner.run(JOB_ID)

    assert rebuild.calls == []
    assert result["index_rebuilt"] is False
    assert result["index_version"] == "redis-existing"
    assert snapshot_store.calls == 1


def test_started_job_resumes_only_pending_items():
    runner, tracker, items, processor, _, _ = runner_fixture()
    tracker.job.status = STARTED_STATUS
    items.pending_ids = [12]
    items.terminal_count = 2

    runner.run(JOB_ID)

    assert processor.processed_ids == [12]
    assert all(call[0] != "claim" for call in tracker.calls)
    assert (
        "progress",
        JOB_ID,
        {
            "progress_current": 3,
            "progress_total": 4,
            "progress_message": "Processed document 3 of 3",
        },
    ) in tracker.calls


def test_successful_redelivery_returns_stored_result_without_work():
    runner, tracker, items, processor, rebuild, _ = runner_fixture()
    tracker.job.status = SUCCESS_STATUS
    tracker.job.result = SUCCESS_RESULT

    assert runner.run(JOB_ID) == SUCCESS_RESULT
    assert processor.processed_ids == []
    assert rebuild.calls == []
    assert items.calls == []
    assert tracker.calls == [("get", JOB_ID)]


def test_failed_job_rejects_redelivery_without_work():
    runner, tracker, _, processor, rebuild, _ = runner_fixture()
    tracker.job.status = FAILURE_STATUS

    with pytest.raises(JobTransitionError, match="already failed"):
        runner.run(JOB_ID)

    assert processor.processed_ids == []
    assert rebuild.calls == []


@pytest.mark.parametrize(
    "job",
    [
        None,
        SimpleNamespace(
            id=JOB_ID,
            job_type=SEARCH_INDEX_REBUILD_JOB,
            status=PENDING_STATUS,
            progress_total=4,
            result=None,
        ),
    ],
    ids=["missing", "wrong-type"],
)
def test_missing_or_wrong_type_job_is_rejected(job):
    runner, tracker, _, processor, _, _ = runner_fixture()
    tracker.job = job

    with pytest.raises(JobTransitionError, match="missing or invalid"):
        runner.run(JOB_ID)

    assert processor.processed_ids == []


@pytest.mark.parametrize("progress_total", [None, 0, 1])
def test_invalid_progress_metadata_is_rejected(progress_total):
    runner, tracker, _, processor, _, _ = runner_fixture()
    tracker.job.progress_total = progress_total

    with pytest.raises(JobTransitionError, match="invalid progress metadata"):
        runner.run(JOB_ID)

    assert processor.processed_ids == []


def test_unclaimable_pending_job_is_rejected_without_work():
    runner, tracker, _, processor, _, _ = runner_fixture()
    tracker.claimed = False

    with pytest.raises(JobTransitionError, match="could not be claimed"):
        runner.run(JOB_ID)

    assert processor.processed_ids == []


def test_rebuild_failure_propagates_without_marking_success():
    runner, tracker, _, _, rebuild, _ = runner_fixture()
    rebuild.error = ConnectionError("redis unavailable")

    with pytest.raises(ConnectionError, match="redis unavailable"):
        runner.run(JOB_ID)

    assert rebuild.calls == [{"index_version": f"redis-{JOB_ID}"}]
    assert all(call[0] != "success" for call in tracker.calls)


class StoreSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class StoreRepository:
    def __init__(self, session: StoreSession) -> None:
        self.session = session

    def list_pending_ids(self, job_id: UUID) -> list[int]:
        return [10, 12]

    def count_terminal(self, job_id: UUID) -> int:
        return 1

    def counts(self, job_id: UUID) -> IngestionCounts:
        return IngestionCounts(received=3, imported=1, skipped=1, failed=1)


def test_item_store_uses_a_fresh_short_session_for_each_read():
    sessions = []

    def session_factory():
        session = StoreSession()
        sessions.append(session)
        return session

    store = IngestionItemStore(
        session_factory=session_factory,
        repository_factory=StoreRepository,
    )

    assert store.list_pending_ids(JOB_ID) == [10, 12]
    assert store.count_terminal(JOB_ID) == 1
    assert store.counts(JOB_ID).received == 3
    assert len(sessions) == 3
    assert all(session.closed for session in sessions)
