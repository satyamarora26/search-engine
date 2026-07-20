import pytest

from app.services.jobs import JobEnqueueError, JobService


class FakeQueuedTask:
    id = "c241dbf0-2d4e-4b91-9ad7-ce097a543bbd"


class FakeTaskSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def delay(self) -> FakeQueuedTask:
        if self.error:
            raise self.error
        return FakeQueuedTask()


class FakeAsyncResult:
    def __init__(self, state: str, result=None) -> None:
        self.state = state
        self.result = result

    def ready(self) -> bool:
        return self.state in {"SUCCESS", "FAILURE"}


def test_enqueue_search_rebuild_returns_task_id():
    service = JobService(FakeTaskSender(), lambda task_id: None)

    assert service.enqueue_search_index_rebuild() == FakeQueuedTask.id


def test_enqueue_search_rebuild_hides_broker_exception():
    service = JobService(
        FakeTaskSender(ConnectionError("redis password leaked")),
        lambda task_id: None,
    )

    with pytest.raises(
        JobEnqueueError,
        match="Could not enqueue background job.",
    ):
        service.enqueue_search_index_rebuild()


def test_successful_job_status_includes_result():
    service = JobService(
        FakeTaskSender(),
        lambda task_id: FakeAsyncResult(
            "SUCCESS",
            {"index_version": "redis-task-123", "document_count": 2},
        ),
    )

    status = service.get_job_status(FakeQueuedTask.id)

    assert status.status == "SUCCESS"
    assert status.ready is True
    assert status.successful is True
    assert status.result == {
        "index_version": "redis-task-123",
        "document_count": 2,
    }
    assert status.error is None


def test_failed_job_status_hides_raw_exception():
    service = JobService(
        FakeTaskSender(),
        lambda task_id: FakeAsyncResult(
            "FAILURE",
            RuntimeError("database password leaked"),
        ),
    )

    status = service.get_job_status(FakeQueuedTask.id)

    assert status.status == "FAILURE"
    assert status.ready is True
    assert status.successful is False
    assert status.result is None
    assert status.error == "Background job failed."


@pytest.mark.parametrize("task_state", ["PENDING", "STARTED", "RETRY"])
def test_unfinished_job_states_are_preserved(task_state):
    service = JobService(
        FakeTaskSender(),
        lambda task_id: FakeAsyncResult(task_state),
    )

    status = service.get_job_status(FakeQueuedTask.id)

    assert status.status == task_state
    assert status.ready is False
    assert status.successful is False
    assert status.result is None
    assert status.error is None
