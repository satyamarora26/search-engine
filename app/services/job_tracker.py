from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.jobs import JobRepository


class JobTransitionError(Exception):
    pass


class JobTracker:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        repository_factory: Callable[[Session], JobRepository] = JobRepository,
    ) -> None:
        self.session_factory = session_factory
        self.repository_factory = repository_factory

    def claim(
        self,
        job_id: UUID,
        *,
        progress_current: int,
        progress_total: int | None,
        progress_message: str,
    ) -> bool:
        return self._write(
            lambda repository: repository.claim(
                job_id,
                progress_current=progress_current,
                progress_total=progress_total,
                progress_message=progress_message,
            )
        )

    def update_progress(
        self,
        job_id: UUID,
        *,
        progress_current: int,
        progress_total: int | None,
        progress_message: str,
    ) -> None:
        changed = self._write(
            lambda repository: repository.update_progress(
                job_id,
                progress_current=progress_current,
                progress_total=progress_total,
                progress_message=progress_message,
            )
        )
        if not changed:
            raise JobTransitionError("Job rejected progress update.")

    def mark_success(
        self,
        job_id: UUID,
        *,
        result: dict[str, Any],
        progress_total: int,
        progress_message: str,
    ) -> None:
        changed = self._write(
            lambda repository: repository.mark_success(
                job_id,
                result=result,
                progress_total=progress_total,
                progress_message=progress_message,
            )
        )
        if not changed:
            raise JobTransitionError("Job rejected successful completion.")

    def mark_failure(self, job_id: UUID, *, error: str) -> bool:
        return self._write(
            lambda repository: repository.mark_failure(job_id, error=error)
        )

    def _write(self, operation: Callable[[JobRepository], object | None]) -> bool:
        session = self.session_factory()
        try:
            changed = operation(self.repository_factory(session)) is not None
            session.commit()
            return changed
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
