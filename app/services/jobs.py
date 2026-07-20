from collections.abc import Callable
from typing import Any, Protocol

from celery import states

from app.schemas.jobs import JobStatusResponse
from app.workers.celery_app import celery_app
from app.workers.search_tasks import rebuild_search_index_snapshot_task


class JobEnqueueError(Exception):
    pass


class QueuedTask(Protocol):
    id: str


class TaskSender(Protocol):
    def delay(self) -> QueuedTask: ...


class TaskResult(Protocol):
    state: str
    result: Any

    def ready(self) -> bool: ...


class JobService:
    def __init__(
        self,
        rebuild_task: TaskSender,
        result_factory: Callable[[str], TaskResult],
    ) -> None:
        self.rebuild_task = rebuild_task
        self.result_factory = result_factory

    def enqueue_search_index_rebuild(self) -> str:
        try:
            return str(self.rebuild_task.delay().id)
        except Exception as error:
            raise JobEnqueueError("Could not enqueue background job.") from error

    def get_job_status(self, task_id: str) -> JobStatusResponse:
        task = self.result_factory(task_id)
        task_state = str(task.state)
        is_success = task_state == states.SUCCESS
        return JobStatusResponse(
            task_id=task_id,
            status=task_state,
            ready=task.ready(),
            successful=is_success,
            result=(
                task.result
                if is_success and isinstance(task.result, dict)
                else None
            ),
            error=(
                "Background job failed."
                if task_state == states.FAILURE
                else None
            ),
        )


def get_job_service() -> JobService:
    return JobService(rebuild_search_index_snapshot_task, celery_app.AsyncResult)
