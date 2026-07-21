from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.job import (
    ACTIVE_STATUSES,
    FAILURE_STATUS,
    PENDING_STATUS,
    STARTED_STATUS,
    SUCCESS_STATUS,
    Job,
)


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_pending(
        self,
        job_id: UUID,
        *,
        job_type: str,
        resource_key: str | None = None,
        progress_total: int | None,
        progress_message: str | None,
    ) -> Job:
        job = Job(
            id=job_id,
            job_type=job_type,
            resource_key=resource_key,
            status=PENDING_STATUS,
            progress_current=0,
            progress_total=progress_total,
            progress_message=progress_message,
        )
        self.session.add(job)
        self.session.flush()
        self.session.refresh(job)
        return job

    def get(self, job_id: UUID) -> Job | None:
        statement = select(Job).where(Job.id == job_id)
        return self.session.scalars(statement).one_or_none()

    def get_active_by_type(self, job_type: str) -> Job | None:
        statement = select(Job).where(
            Job.job_type == job_type,
            Job.status.in_(ACTIVE_STATUSES),
        )
        return self.session.scalars(statement).one_or_none()

    def get_active_by_resource(self, resource_key: str) -> Job | None:
        statement = select(Job).where(
            Job.resource_key == resource_key,
            Job.status.in_(ACTIVE_STATUSES),
        )
        return self.session.scalars(statement).one_or_none()

    def claim(
        self,
        job_id: UUID,
        *,
        progress_current: int,
        progress_total: int | None,
        progress_message: str,
    ) -> Job | None:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == PENDING_STATUS)
            .values(
                status=STARTED_STATUS,
                progress_current=progress_current,
                progress_total=progress_total,
                progress_message=progress_message,
                started_at=func.now(),
                updated_at=func.now(),
            )
            .returning(Job)
        )
        return self.session.scalars(statement).one_or_none()

    def update_progress(
        self,
        job_id: UUID,
        *,
        progress_current: int,
        progress_total: int | None,
        progress_message: str,
    ) -> Job | None:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == STARTED_STATUS)
            .values(
                progress_current=progress_current,
                progress_total=progress_total,
                progress_message=progress_message,
                updated_at=func.now(),
            )
            .returning(Job)
        )
        return self.session.scalars(statement).one_or_none()

    def mark_success(
        self,
        job_id: UUID,
        *,
        result: dict[str, Any],
        progress_total: int,
        progress_message: str,
    ) -> Job | None:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == STARTED_STATUS)
            .values(
                status=SUCCESS_STATUS,
                progress_current=progress_total,
                progress_total=progress_total,
                progress_message=progress_message,
                result=result,
                error=None,
                finished_at=func.now(),
                updated_at=func.now(),
            )
            .returning(Job)
        )
        return self.session.scalars(statement).one_or_none()

    def mark_failure(self, job_id: UUID, *, error: str) -> Job | None:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status.in_(ACTIVE_STATUSES))
            .values(
                status=FAILURE_STATUS,
                result=None,
                error=error,
                finished_at=func.now(),
                updated_at=func.now(),
            )
            .returning(Job)
        )
        return self.session.scalars(statement).one_or_none()

    def mark_pending_failure(
        self,
        job_id: UUID,
        *,
        error: str,
    ) -> Job | None:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == PENDING_STATUS)
            .values(
                status=FAILURE_STATUS,
                result=None,
                error=error,
                finished_at=func.now(),
                updated_at=func.now(),
            )
            .returning(Job)
        )
        return self.session.scalars(statement).one_or_none()
