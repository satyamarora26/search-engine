# PostgreSQL Job Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Celery-result-backed job status with durable PostgreSQL job records, observable rebuild progress, duplicate rebuild suppression, and explicit worker lifecycle updates.

**Architecture:** PostgreSQL becomes the source of truth for job identity and state while Redis remains the Celery broker/result backend and search-snapshot store. The API creates one UUID shared by the job row and Celery task, repositories enforce conditional state transitions, and the worker records progress through short database transactions before publishing the existing versioned Redis snapshot.

**Tech Stack:** Python 3.13, FastAPI 0.139, Pydantic 2.10, SQLAlchemy 2.0, Alembic, PostgreSQL 16, psycopg 3, Celery 5.6, Redis, pytest.

## Global Constraints

- PostgreSQL is the durable job-status source of truth; `GET /api/v1/jobs/{job_id}` must not call `Celery.AsyncResult`.
- One UUID is shared by the public API job, PostgreSQL row, Celery task, logs, and `redis-{job_id}` index version.
- Public API fields use `job_id`, not `task_id`.
- Public states are exactly `PENDING`, `STARTED`, `SUCCESS`, and `FAILURE`.
- Only one `search_index_rebuild` job may be `PENDING` or `STARTED`.
- State transitions are limited to `PENDING -> STARTED`, `PENDING -> FAILURE`, `STARTED -> SUCCESS`, and `STARTED -> FAILURE`.
- `SUCCESS` and `FAILURE` are immutable terminal states.
- Progress uses nonnegative `progress_current`, nullable positive `progress_total`, and a sanitized message; current cannot exceed a known total.
- Raw database, Redis, broker, and worker exception text must never enter stored public errors or API responses.
- Do not add automatic retries, cancellation, cleanup, stale-job recovery, job listing, or a transactional outbox in this slice.
- Existing Redis snapshot publication ordering and fail-open search activation behavior must remain unchanged.
- Use TDD for every production behavior: write a failing test, observe the expected failure, implement the minimum behavior, and rerun the focused test.
- Commit and push every completed task to `origin/main`.

## File Map

- `app/models/job.py`: SQLAlchemy job table, constants, constraints, and indexes.
- `alembic/versions/20260721_0002_create_jobs.py`: PostgreSQL migration for durable jobs.
- `app/repositories/jobs.py`: job reads and atomic conditional state mutations.
- `app/schemas/jobs.py`: accepted-job, progress, and status response contracts.
- `app/services/jobs.py`: duplicate-safe durable enqueue and job lookup orchestration.
- `app/services/job_tracker.py`: short worker-owned transactions around repository updates.
- `app/workers/search_tasks.py`: tracked search-index rebuild orchestration.
- `app/api/dependencies.py`: shared FastAPI construction of `JobService`.
- `app/api/v1/search.py`: durable rebuild enqueue response.
- `app/api/v1/jobs.py`: PostgreSQL-backed status endpoint and HTTP error mapping.
- `tests/unit/test_job_model.py`: model and PostgreSQL DDL contract.
- `tests/unit/test_job_repository.py`: repository statement and transition guards.
- `tests/unit/test_jobs.py`: service enqueue, duplicate, and response behavior.
- `tests/unit/test_job_tracker.py`: worker transaction ownership.
- `tests/unit/test_worker_search_tasks.py`: worker lifecycle and failure behavior.
- `tests/integration/test_job_api.py`: HTTP contract using a fake service.
- `tests/integration/test_job_repository_postgres.py`: live PostgreSQL constraints and transitions.
- `tests/integration/test_job_api_postgres.py`: real PostgreSQL API persistence and 404 behavior.
- `docs/job-tracking.md`: local usage, lifecycle, and operational limitations.

---

### Task 1: Job Model And Alembic Migration

**Files:**
- Create: `app/models/job.py`
- Create: `alembic/versions/20260721_0002_create_jobs.py`
- Modify: `alembic/env.py:8-10`
- Create: `tests/unit/test_job_model.py`

**Interfaces:**
- Produces: `Job` mapped to PostgreSQL table `jobs`.
- Produces: constants `SEARCH_INDEX_REBUILD_JOB`, `PENDING_STATUS`, `STARTED_STATUS`, `SUCCESS_STATUS`, `FAILURE_STATUS`, and `ACTIVE_STATUSES`.
- Produces: Alembic revision `20260721_0002`, based on `20260720_0001`.

- [ ] **Step 1: Write the failing job-model tests**

Create `tests/unit/test_job_model.py`:

```python
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.job import Job


def test_job_model_uses_durable_job_columns():
    assert Job.__tablename__ == "jobs"
    assert {
        "id",
        "job_type",
        "status",
        "progress_current",
        "progress_total",
        "progress_message",
        "result",
        "error",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    } == set(Job.__table__.columns.keys())


def test_job_model_declares_state_progress_and_active_rebuild_guards():
    constraint_names = {constraint.name for constraint in Job.__table__.constraints}
    index_names = {index.name for index in Job.__table__.indexes}

    assert "jobs_status_check" in constraint_names
    assert "jobs_progress_current_check" in constraint_names
    assert "jobs_progress_total_check" in constraint_names
    assert "jobs_progress_bounds_check" in constraint_names
    assert "jobs_one_active_search_index_rebuild_idx" in index_names


def test_job_model_compiles_postgresql_uuid_jsonb_and_timestamps():
    sql = str(CreateTable(Job.__table__).compile(dialect=postgresql.dialect()))

    assert "CREATE TABLE jobs" in sql
    assert "UUID NOT NULL" in sql
    assert "JSONB" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
```

- [ ] **Step 2: Run the model tests and observe RED**

Run:

```bash
pytest tests/unit/test_job_model.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.models.job'`.

- [ ] **Step 3: Implement the SQLAlchemy job model**

Create `app/models/job.py`:

```python
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SEARCH_INDEX_REBUILD_JOB = "search_index_rebuild"
PENDING_STATUS = "PENDING"
STARTED_STATUS = "STARTED"
SUCCESS_STATUS = "SUCCESS"
FAILURE_STATUS = "FAILURE"
ACTIVE_STATUSES = (PENDING_STATUS, STARTED_STATUS)
TERMINAL_STATUSES = (SUCCESS_STATUS, FAILURE_STATUS)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status in ('PENDING', 'STARTED', 'SUCCESS', 'FAILURE')",
            name="jobs_status_check",
        ),
        CheckConstraint(
            "progress_current >= 0",
            name="jobs_progress_current_check",
        ),
        CheckConstraint(
            "progress_total is null or progress_total > 0",
            name="jobs_progress_total_check",
        ),
        CheckConstraint(
            "progress_total is null or progress_current <= progress_total",
            name="jobs_progress_bounds_check",
        ),
        Index("jobs_status_created_at_idx", "status", "created_at"),
        Index(
            "jobs_one_active_search_index_rebuild_idx",
            "job_type",
            unique=True,
            postgresql_where=text(
                "job_type = 'search_index_rebuild' "
                "and status in ('PENDING', 'STARTED')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=PENDING_STATUS,
    )
    progress_current: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default="0",
    )
    progress_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

- [ ] **Step 4: Add the Alembic migration and metadata import**

Create `alembic/versions/20260721_0002_create_jobs.py`:

```python
"""create jobs table

Revision ID: 20260721_0002
Revises: 20260720_0001
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260721_0002"
down_revision: str | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column(
            "progress_current",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("progress_total", sa.BigInteger(), nullable=True),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('PENDING', 'STARTED', 'SUCCESS', 'FAILURE')",
            name="jobs_status_check",
        ),
        sa.CheckConstraint(
            "progress_current >= 0",
            name="jobs_progress_current_check",
        ),
        sa.CheckConstraint(
            "progress_total is null or progress_total > 0",
            name="jobs_progress_total_check",
        ),
        sa.CheckConstraint(
            "progress_total is null or progress_current <= progress_total",
            name="jobs_progress_bounds_check",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "jobs_status_created_at_idx",
        "jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "jobs_one_active_search_index_rebuild_idx",
        "jobs",
        ["job_type"],
        unique=True,
        postgresql_where=sa.text(
            "job_type = 'search_index_rebuild' "
            "and status in ('PENDING', 'STARTED')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "jobs_one_active_search_index_rebuild_idx",
        table_name="jobs",
    )
    op.drop_index("jobs_status_created_at_idx", table_name="jobs")
    op.drop_table("jobs")
```

Add this import beside the `Document` import in `alembic/env.py`:

```python
from app.models.job import Job
```

- [ ] **Step 5: Run focused verification and observe GREEN**

Run:

```bash
pytest tests/unit/test_job_model.py tests/unit/test_document_model.py -v
alembic upgrade head --sql
git diff --check
```

Expected: model tests pass, offline migration SQL includes `CREATE TABLE jobs`, and `git diff --check` exits `0`.

- [ ] **Step 6: Commit and push Task 1**

```bash
git add app/models/job.py alembic/env.py alembic/versions/20260721_0002_create_jobs.py tests/unit/test_job_model.py
git commit -m "feat: add durable job database model"
git push origin main
```

---

### Task 2: Atomic Job Repository

**Files:**
- Create: `app/repositories/jobs.py`
- Create: `tests/unit/test_job_repository.py`

**Interfaces:**
- Consumes: `Job` and job constants from Task 1.
- Produces: `JobRepository.create_pending(job_id: UUID, *, job_type: str, progress_total: int | None, progress_message: str | None) -> Job`.
- Produces: `JobRepository.get(job_id: UUID) -> Job | None`.
- Produces: `JobRepository.get_active(job_type: str) -> Job | None`.
- Produces: `JobRepository.claim(job_id: UUID, *, progress_current: int, progress_total: int | None, progress_message: str) -> Job | None`.
- Produces: `JobRepository.update_progress(job_id: UUID, *, progress_current: int, progress_total: int | None, progress_message: str) -> Job | None`.
- Produces: `JobRepository.mark_success(job_id: UUID, *, result: dict[str, Any], progress_total: int, progress_message: str) -> Job | None`.
- Produces: `JobRepository.mark_failure(job_id: UUID, *, error: str) -> Job | None`.

- [ ] **Step 1: Write failing repository tests**

Create `tests/unit/test_job_repository.py`:

```python
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.models.job import Job, PENDING_STATUS, SEARCH_INDEX_REBUILD_JOB
from app.repositories.jobs import JobRepository

JOB_ID = UUID("c241dbf0-2d4e-4b91-9ad7-ce097a543bbd")


class FakeScalarResult:
    def __init__(self, one: Job | None = None) -> None:
        self.one = one

    def one_or_none(self) -> Job | None:
        return self.one


class FakeSession:
    def __init__(self, result: FakeScalarResult | None = None) -> None:
        self.result = result or FakeScalarResult()
        self.added: list[Job] = []
        self.flushed = False
        self.refreshed: list[Job] = []
        self.statements = []

    def add(self, instance: Job) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        self.flushed = True

    def refresh(self, instance: Job) -> None:
        self.refreshed.append(instance)

    def scalars(self, statement):
        self.statements.append(statement)
        return self.result


def compile_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_create_pending_adds_and_flushes_caller_owned_uuid():
    session = FakeSession()
    repository = JobRepository(session)

    job = repository.create_pending(
        JOB_ID,
        job_type=SEARCH_INDEX_REBUILD_JOB,
        progress_total=4,
        progress_message="Waiting for worker",
    )

    assert job.id == JOB_ID
    assert job.status == PENDING_STATUS
    assert job.progress_current == 0
    assert session.added == [job]
    assert session.flushed is True
    assert session.refreshed == [job]


def test_get_active_filters_by_type_and_nonterminal_states():
    expected = Job(id=JOB_ID, job_type=SEARCH_INDEX_REBUILD_JOB)
    session = FakeSession(FakeScalarResult(expected))

    assert JobRepository(session).get_active(SEARCH_INDEX_REBUILD_JOB) is expected
    sql = compile_sql(session.statements[0])
    assert "jobs.job_type = 'search_index_rebuild'" in sql
    assert "jobs.status IN ('PENDING', 'STARTED')" in sql


def test_claim_is_guarded_by_pending_status():
    session = FakeSession(FakeScalarResult(Job(id=JOB_ID)))

    JobRepository(session).claim(
        JOB_ID,
        progress_current=1,
        progress_total=4,
        progress_message="Loading documents",
    )

    sql = compile_sql(session.statements[0])
    assert "jobs.id = 'c241dbf0-2d4e-4b91-9ad7-ce097a543bbd'" in sql
    assert "jobs.status = 'PENDING'" in sql
    assert "RETURNING" in sql


def test_progress_and_success_are_guarded_by_started_status():
    session = FakeSession(FakeScalarResult(Job(id=JOB_ID)))
    repository = JobRepository(session)

    repository.update_progress(
        JOB_ID,
        progress_current=2,
        progress_total=4,
        progress_message="Building search index",
    )
    repository.mark_success(
        JOB_ID,
        result={"index_version": f"redis-{JOB_ID}", "document_count": 2},
        progress_total=4,
        progress_message="Search index rebuilt",
    )

    progress = session.statements[0].compile(dialect=postgresql.dialect())
    success = session.statements[1].compile(dialect=postgresql.dialect())
    assert "STARTED" in progress.params.values()
    assert "STARTED" in success.params.values()


def test_failure_accepts_only_pending_or_started_jobs():
    session = FakeSession(FakeScalarResult(Job(id=JOB_ID)))

    JobRepository(session).mark_failure(
        JOB_ID,
        error="Search index rebuild failed.",
    )

    sql = compile_sql(session.statements[0])
    assert "jobs.status IN ('PENDING', 'STARTED')" in sql
```

- [ ] **Step 2: Run repository tests and observe RED**

Run:

```bash
pytest tests/unit/test_job_repository.py -v
```

Expected: collection fails because `app.repositories.jobs` does not exist.

- [ ] **Step 3: Implement the repository state machine**

Create `app/repositories/jobs.py`:

```python
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
        progress_total: int | None,
        progress_message: str | None,
    ) -> Job:
        job = Job(
            id=job_id,
            job_type=job_type,
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
        return self.session.scalars(
            select(Job).where(Job.id == job_id)
        ).one_or_none()

    def get_active(self, job_type: str) -> Job | None:
        statement = select(Job).where(
            Job.job_type == job_type,
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
```

- [ ] **Step 4: Run focused repository tests and observe GREEN**

Run:

```bash
pytest tests/unit/test_job_repository.py tests/unit/test_job_model.py -v
git diff --check
```

Expected: all focused job persistence tests pass and `git diff --check` exits `0`.

- [ ] **Step 5: Commit and push Task 2**

```bash
git add app/repositories/jobs.py tests/unit/test_job_repository.py
git commit -m "feat: add atomic job repository"
git push origin main
```

---
### Task 3: Short-Transaction Worker Job Tracker

**Files:**
- Create: `app/services/job_tracker.py`
- Create: `tests/unit/test_job_tracker.py`

**Interfaces:**
- Consumes: all state mutation methods from `JobRepository` in Task 2.
- Produces: `JobTransitionError` for a rejected required transition.
- Produces: `JobTracker.claim(job_id: UUID, *, progress_current: int, progress_total: int | None, progress_message: str) -> bool`.
- Produces: `JobTracker.update_progress(job_id: UUID, *, progress_current: int, progress_total: int | None, progress_message: str) -> None`.
- Produces: `JobTracker.mark_success(job_id: UUID, *, result: dict[str, Any], progress_total: int, progress_message: str) -> None`.
- Produces: `JobTracker.mark_failure(job_id: UUID, *, error: str) -> bool`.
- Guarantees: every method opens, commits or rolls back, and closes its own SQLAlchemy session.

- [ ] **Step 1: Write failing tracker transaction tests**

Create `tests/unit/test_job_tracker.py`:

```python
from uuid import UUID

import pytest

from app.services.job_tracker import JobTracker, JobTransitionError

JOB_ID = UUID("c241dbf0-2d4e-4b91-9ad7-ce097a543bbd")


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class FakeRepository:
    def __init__(self, session: FakeSession, result=object()) -> None:
        self.session = session
        self.result = result
        self.calls = []
        self.error: Exception | None = None

    def _call(self, name: str, **values):
        self.calls.append((name, values))
        if self.error:
            raise self.error
        return self.result

    def claim(self, job_id, **values):
        return self._call("claim", job_id=job_id, **values)

    def update_progress(self, job_id, **values):
        return self._call("update_progress", job_id=job_id, **values)

    def mark_success(self, job_id, **values):
        return self._call("mark_success", job_id=job_id, **values)

    def mark_failure(self, job_id, **values):
        return self._call("mark_failure", job_id=job_id, **values)


def build_tracker(repository_result=object()):
    sessions = []
    repositories = []

    def session_factory():
        session = FakeSession()
        sessions.append(session)
        return session

    def repository_factory(session):
        repository = FakeRepository(session, repository_result)
        repositories.append(repository)
        return repository

    return JobTracker(session_factory, repository_factory), sessions, repositories


def test_claim_commits_and_closes_a_short_session():
    tracker, sessions, repositories = build_tracker()

    claimed = tracker.claim(
        JOB_ID,
        progress_current=1,
        progress_total=4,
        progress_message="Loading documents",
    )

    assert claimed is True
    assert repositories[0].calls[0][0] == "claim"
    assert sessions[0].commits == 1
    assert sessions[0].rollbacks == 0
    assert sessions[0].closed is True


def test_rejected_required_progress_transition_raises_after_commit():
    tracker, sessions, _ = build_tracker(repository_result=None)

    with pytest.raises(JobTransitionError, match="progress"):
        tracker.update_progress(
            JOB_ID,
            progress_current=2,
            progress_total=4,
            progress_message="Building search index",
        )

    assert sessions[0].commits == 1
    assert sessions[0].closed is True


def test_repository_error_rolls_back_and_closes():
    tracker, sessions, repositories = build_tracker()

    def broken_repository_factory(session):
        repository = FakeRepository(session)
        repository.error = RuntimeError("database failed")
        repositories.append(repository)
        return repository

    tracker.repository_factory = broken_repository_factory

    with pytest.raises(RuntimeError, match="database failed"):
        tracker.mark_failure(JOB_ID, error="Search index rebuild failed.")

    assert sessions[0].rollbacks == 1
    assert sessions[0].closed is True


def test_mark_failure_reports_terminal_or_missing_job_without_raising():
    tracker, sessions, _ = build_tracker(repository_result=None)

    changed = tracker.mark_failure(
        JOB_ID,
        error="Search index rebuild failed.",
    )

    assert changed is False
    assert sessions[0].commits == 1
    assert sessions[0].closed is True
```

- [ ] **Step 2: Run tracker tests and observe RED**

Run:

```bash
pytest tests/unit/test_job_tracker.py -v
```

Expected: collection fails because `app.services.job_tracker` does not exist.

- [ ] **Step 3: Implement short transaction ownership**

Create `app/services/job_tracker.py`:

```python
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
```

- [ ] **Step 4: Run focused tracker tests and observe GREEN**

Run:

```bash
pytest tests/unit/test_job_tracker.py tests/unit/test_job_repository.py -v
git diff --check
```

Expected: all tracker and repository tests pass; each tested transaction closes;
`git diff --check` exits `0`.

- [ ] **Step 5: Commit and push Task 3**

```bash
git add app/services/job_tracker.py tests/unit/test_job_tracker.py
git commit -m "feat: add transactional worker job tracker"
git push origin main
```

---

### Task 4: Tracked Search-Rebuild Worker Lifecycle

**Files:**
- Modify: `app/workers/search_tasks.py:1-52`
- Modify: `tests/unit/test_worker_search_tasks.py`

**Interfaces:**
- Consumes: `JobTracker` from Task 3.
- Preserves: `rebuild_search_index_snapshot(index_version, session_factory, store_factory) -> dict[str, Any]` with an added optional `progress_callback`.
- Produces: `execute_rebuild_search_index_job(job_id: str, celery_task_id: str, ...) -> dict[str, Any]`.
- Changes: Celery task signature to `rebuild_search_index_snapshot_task(task: Task, job_id: str) -> dict[str, Any]`.

- [ ] **Step 1: Add failing worker lifecycle tests**

Keep the existing snapshot helper tests in
`tests/unit/test_worker_search_tasks.py`. Add `execute_rebuild_search_index_job`
to its worker imports and append:

```python
from uuid import UUID

JOB_ID = "c241dbf0-2d4e-4b91-9ad7-ce097a543bbd"


class FakeJobTracker:
    def __init__(self, *, claimed: bool = True) -> None:
        self.claimed = claimed
        self.calls = []

    def claim(self, job_id: UUID, **values) -> bool:
        self.calls.append(("claim", job_id, values))
        return self.claimed

    def update_progress(self, job_id: UUID, **values) -> None:
        self.calls.append(("progress", job_id, values))

    def mark_success(self, job_id: UUID, **values) -> None:
        self.calls.append(("success", job_id, values))

    def mark_failure(self, job_id: UUID, **values) -> bool:
        self.calls.append(("failure", job_id, values))
        return True


def test_execute_rebuild_records_claim_progress_and_success():
    tracker = FakeJobTracker()
    progress_callbacks = []

    def fake_rebuild(index_version, progress_callback=None, **kwargs):
        assert index_version == f"redis-{JOB_ID}"
        progress_callback(2, "Building search index")
        progress_callback(3, "Publishing search snapshot")
        progress_callbacks.extend([2, 3])
        return {"index_version": index_version, "document_count": 7}

    result = execute_rebuild_search_index_job(
        JOB_ID,
        JOB_ID,
        tracker_factory=lambda: tracker,
        rebuild=fake_rebuild,
    )

    assert result["document_count"] == 7
    assert progress_callbacks == [2, 3]
    assert [call[0] for call in tracker.calls] == [
        "claim",
        "progress",
        "progress",
        "success",
    ]
    assert tracker.calls[-1][2]["progress_total"] == 4


def test_execute_rebuild_rejects_duplicate_delivery_before_work():
    tracker = FakeJobTracker(claimed=False)
    rebuild_called = False

    def fake_rebuild(*args, **kwargs):
        nonlocal rebuild_called
        rebuild_called = True

    with pytest.raises(RuntimeError, match="not pending"):
        execute_rebuild_search_index_job(
            JOB_ID,
            JOB_ID,
            tracker_factory=lambda: tracker,
            rebuild=fake_rebuild,
        )

    assert rebuild_called is False
    assert [call[0] for call in tracker.calls] == ["claim"]


def test_execute_rebuild_stores_safe_failure_and_reraises_original_error():
    tracker = FakeJobTracker()

    def broken_rebuild(*args, **kwargs):
        raise ConnectionError("redis password leaked")

    with pytest.raises(ConnectionError, match="redis password leaked"):
        execute_rebuild_search_index_job(
            JOB_ID,
            JOB_ID,
            tracker_factory=lambda: tracker,
            rebuild=broken_rebuild,
        )

    failure = tracker.calls[-1]
    assert failure[0] == "failure"
    assert failure[2]["error"] == "Search index rebuild failed."
    assert "password" not in failure[2]["error"]


def test_execute_rebuild_requires_matching_public_and_celery_ids():
    tracker = FakeJobTracker()

    with pytest.raises(RuntimeError, match="does not match"):
        execute_rebuild_search_index_job(
            JOB_ID,
            "different-task-id",
            tracker_factory=lambda: tracker,
        )

    assert tracker.calls == []
```

Replace the existing wrapper test with:

```python
def test_rebuild_task_passes_matching_celery_and_job_ids(monkeypatch):
    called_with = []

    def fake_execute(job_id: str, celery_task_id: str):
        called_with.append((job_id, celery_task_id))
        return {"index_version": f"redis-{job_id}", "document_count": 0}

    monkeypatch.setattr(
        "app.workers.search_tasks.execute_rebuild_search_index_job",
        fake_execute,
    )

    result = rebuild_search_index_snapshot_task.apply(
        args=[JOB_ID],
        task_id=JOB_ID,
    )

    assert result.successful() is True
    assert called_with == [(JOB_ID, JOB_ID)]
```

- [ ] **Step 2: Run worker tests and observe RED**

Run:

```bash
pytest tests/unit/test_worker_search_tasks.py -v
```

Expected: collection fails because `execute_rebuild_search_index_job` is not
defined, and the existing Celery task does not accept the job-id argument.

- [ ] **Step 3: Implement explicit tracked orchestration**

Update `app/workers/search_tasks.py` so its imports and functions are:

```python
from collections.abc import Callable
import logging
from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.documents import DocumentRepository
from app.schemas.search_snapshots import (
    SearchIndexSnapshot,
    SearchSnapshotDocument,
)
from app.services.job_tracker import JobTracker
from app.services.search_index import SearchIndexService
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
REBUILD_PROGRESS_TOTAL = 4


def rebuild_search_index_snapshot(
    index_version: str,
    session_factory: Callable[[], Session] = SessionLocal,
    store_factory: Callable[
        [], RedisSearchIndexStore
    ] = create_redis_search_index_store,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    session = session_factory()
    try:
        documents = DocumentRepository(session).list_all_active()
        if progress_callback is not None:
            progress_callback(2, "Building search index")

        status = SearchIndexService(
            documents,
            index_version=index_version,
        ).status()
        snapshot = SearchIndexSnapshot(
            index_version=index_version,
            documents=[
                SearchSnapshotDocument.model_validate(document)
                for document in documents
            ],
        )
        if progress_callback is not None:
            progress_callback(3, "Publishing search snapshot")

        store_factory().publish(snapshot)
        return status.model_dump()
    finally:
        session.close()


def execute_rebuild_search_index_job(
    job_id: str,
    celery_task_id: str,
    *,
    tracker_factory: Callable[[], JobTracker] = JobTracker,
    rebuild: Callable[..., dict[str, Any]] = rebuild_search_index_snapshot,
) -> dict[str, Any]:
    if job_id != celery_task_id:
        raise RuntimeError("Celery task id does not match durable job id.")

    durable_job_id = UUID(job_id)
    tracker = tracker_factory()
    claimed = tracker.claim(
        durable_job_id,
        progress_current=1,
        progress_total=REBUILD_PROGRESS_TOTAL,
        progress_message="Loading documents",
    )
    if not claimed:
        raise RuntimeError("Durable job is missing or not pending.")

    try:
        result = rebuild(
            f"redis-{job_id}",
            progress_callback=lambda current, message: tracker.update_progress(
                durable_job_id,
                progress_current=current,
                progress_total=REBUILD_PROGRESS_TOTAL,
                progress_message=message,
            ),
        )
        tracker.mark_success(
            durable_job_id,
            result=result,
            progress_total=REBUILD_PROGRESS_TOTAL,
            progress_message="Search index rebuilt",
        )
        return result
    except Exception:
        logger.exception("Search index rebuild job %s failed.", job_id)
        try:
            tracker.mark_failure(
                durable_job_id,
                error="Search index rebuild failed.",
            )
        except Exception:
            logger.exception("Could not record failure for job %s.", job_id)
        raise


@celery_app.task(bind=True, name="search.rebuild_index_snapshot")
def rebuild_search_index_snapshot_task(
    task: Task,
    job_id: str,
) -> dict[str, Any]:
    if task.request.id is None:
        raise RuntimeError("Celery rebuild task id is required.")
    return execute_rebuild_search_index_job(job_id, str(task.request.id))
```

- [ ] **Step 4: Run worker and tracker tests and observe GREEN**

Run:

```bash
pytest tests/unit/test_worker_search_tasks.py tests/unit/test_job_tracker.py -v
pytest tests/unit/test_celery_config.py -v
git diff --check
```

Expected: worker lifecycle, failure, duplicate-delivery, session-closure, stable
task-name, and Celery configuration tests all pass.

- [ ] **Step 5: Commit and push Task 4**

```bash
git add app/workers/search_tasks.py tests/unit/test_worker_search_tasks.py
git commit -m "feat: track search rebuild job lifecycle"
git push origin main
```

---
### Task 5: Durable Job Service And HTTP Contract

**Files:**
- Replace: `app/schemas/jobs.py`
- Replace: `app/services/jobs.py`
- Create: `app/api/dependencies.py`
- Modify: `app/api/v1/jobs.py:1-16`
- Modify: `app/api/v1/search.py:3-59`
- Replace: `tests/unit/test_jobs.py`
- Replace: `tests/integration/test_job_api.py`

**Interfaces:**
- Consumes: `JobRepository` from Task 2 and the tracked Celery task from Task 4.
- Produces: `JobService.enqueue_search_index_rebuild() -> Job`.
- Produces: `JobService.get_job(job_id: UUID) -> Job`.
- Produces: `JobNotFoundError`, `JobStorageError`, and `JobEnqueueError` with stable public messages.
- Produces: `JobStatusResponse.from_job(job: Job) -> JobStatusResponse`.
- Produces: FastAPI dependency `get_job_service(session: Session) -> JobService`.
- Changes: accepted and status responses expose `job_id`; status lookup reads PostgreSQL only.

- [ ] **Step 1: Write failing schema and service tests**

Replace `tests/unit/test_jobs.py` with:

```python
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.job import (
    PENDING_STATUS,
    SEARCH_INDEX_REBUILD_JOB,
    STARTED_STATUS,
    Job,
)
from app.schemas.jobs import JobStatusResponse
from app.services.jobs import (
    JobEnqueueError,
    JobNotFoundError,
    JobService,
    JobStorageError,
)

JOB_ID = UUID("c241dbf0-2d4e-4b91-9ad7-ce097a543bbd")


def build_job(*, status: str = PENDING_STATUS) -> Job:
    return Job(
        id=JOB_ID,
        job_type=SEARCH_INDEX_REBUILD_JOB,
        status=status,
        progress_current=2 if status == STARTED_STATUS else 0,
        progress_total=4,
        progress_message=(
            "Building search index" if status == STARTED_STATUS else "Waiting for worker"
        ),
        created_at=datetime(2026, 7, 21, 10, 0, tzinfo=UTC),
        started_at=(
            datetime(2026, 7, 21, 10, 1, tzinfo=UTC)
            if status == STARTED_STATUS
            else None
        ),
        updated_at=datetime(2026, 7, 21, 10, 1, tzinfo=UTC),
    )


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeTaskSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    def apply_async(self, *, args: list[str], task_id: str):
        self.calls.append({"args": args, "task_id": task_id})
        if self.error:
            raise self.error
        return object()


class FakeJobRepository:
    def __init__(self) -> None:
        self.active_results: list[Job | None] = [None]
        self.job: Job | None = None
        self.get_error: Exception | None = None
        self.create_error: Exception | None = None
        self.created_with = None
        self.failed_with = None

    def get_active(self, job_type: str) -> Job | None:
        if self.get_error:
            raise self.get_error
        return self.active_results.pop(0)

    def create_pending(self, job_id: UUID, **values) -> Job:
        if self.create_error:
            raise self.create_error
        self.created_with = {"job_id": job_id, **values}
        self.job = build_job()
        return self.job

    def get(self, job_id: UUID) -> Job | None:
        if self.get_error:
            raise self.get_error
        return self.job

    def mark_failure(self, job_id: UUID, *, error: str) -> Job | None:
        self.failed_with = {"job_id": job_id, "error": error}
        return self.job


def build_service(session, task, repository) -> JobService:
    return JobService(
        session,
        task,
        job_id_factory=lambda: JOB_ID,
        repository=repository,
    )


def test_enqueue_commits_job_then_sends_same_uuid_to_celery():
    session = FakeSession()
    task = FakeTaskSender()
    repository = FakeJobRepository()

    job = build_service(session, task, repository).enqueue_search_index_rebuild()

    assert job.id == JOB_ID
    assert session.commits == 1
    assert repository.created_with == {
        "job_id": JOB_ID,
        "job_type": SEARCH_INDEX_REBUILD_JOB,
        "progress_total": 4,
        "progress_message": "Waiting for worker",
    }
    assert task.calls == [{"args": [str(JOB_ID)], "task_id": str(JOB_ID)}]


def test_enqueue_returns_existing_active_job_without_sending_task():
    session = FakeSession()
    task = FakeTaskSender()
    repository = FakeJobRepository()
    existing = build_job(status=STARTED_STATUS)
    repository.active_results = [existing]

    job = build_service(session, task, repository).enqueue_search_index_rebuild()

    assert job is existing
    assert session.commits == 0
    assert task.calls == []


def test_unique_insert_race_returns_winning_active_job():
    session = FakeSession()
    repository = FakeJobRepository()
    winner = build_job(status=STARTED_STATUS)
    repository.active_results = [None, winner]
    repository.create_error = IntegrityError("unique", {}, Exception())

    job = build_service(
        session,
        FakeTaskSender(),
        repository,
    ).enqueue_search_index_rebuild()

    assert job is winner
    assert session.rollbacks == 1


def test_broker_failure_marks_job_failed_without_storing_raw_error():
    session = FakeSession()
    repository = FakeJobRepository()
    task = FakeTaskSender(ConnectionError("redis password leaked"))

    with pytest.raises(JobEnqueueError, match="Could not enqueue background job"):
        build_service(session, task, repository).enqueue_search_index_rebuild()

    assert repository.failed_with == {
        "job_id": JOB_ID,
        "error": "Could not enqueue background job.",
    }
    assert "password" not in repository.failed_with["error"]
    assert session.commits == 2


def test_get_unknown_job_raises_not_found():
    repository = FakeJobRepository()

    with pytest.raises(JobNotFoundError, match=str(JOB_ID)):
        build_service(
            FakeSession(),
            FakeTaskSender(),
            repository,
        ).get_job(JOB_ID)


def test_database_error_is_mapped_to_stable_storage_error():
    repository = FakeJobRepository()
    repository.get_error = SQLAlchemyError("database password leaked")

    with pytest.raises(JobStorageError, match="Job storage unavailable") as caught:
        build_service(
            FakeSession(),
            FakeTaskSender(),
            repository,
        ).get_job(JOB_ID)

    assert "password" not in str(caught.value)


def test_enqueue_database_failure_never_sends_celery_task():
    repository = FakeJobRepository()
    repository.get_error = SQLAlchemyError("database unavailable")
    task = FakeTaskSender()

    with pytest.raises(JobStorageError, match="Job storage unavailable"):
        build_service(FakeSession(), task, repository).enqueue_search_index_rebuild()

    assert task.calls == []


def test_status_response_derives_progress_and_readiness_from_job():
    response = JobStatusResponse.from_job(build_job(status=STARTED_STATUS))

    assert response.job_id == JOB_ID
    assert response.ready is False
    assert response.successful is False
    assert response.progress.current == 2
    assert response.progress.total == 4
    assert response.progress.percentage == 50.0
    assert response.progress.message == "Building search index"


def test_terminal_status_response_is_ready_and_preserves_structured_result():
    job = build_job()
    job.status = "SUCCESS"
    job.progress_current = 4
    job.result = {"index_version": f"redis-{JOB_ID}", "document_count": 5}

    response = JobStatusResponse.from_job(job)

    assert response.ready is True
    assert response.successful is True
    assert response.result == job.result


def test_unknown_progress_total_has_no_percentage():
    job = build_job(status=STARTED_STATUS)
    job.progress_total = None

    assert JobStatusResponse.from_job(job).progress.percentage is None
```

- [ ] **Step 2: Run service tests and observe RED**

Run:

```bash
pytest tests/unit/test_jobs.py -v
```

Expected: tests fail because current schemas use `task_id`, the service reads
Celery `AsyncResult`, and its constructor has no SQLAlchemy session or repository.

- [ ] **Step 3: Implement durable response schemas**

Replace `app/schemas/jobs.py` with:

```python
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel

from app.models.job import SUCCESS_STATUS, TERMINAL_STATUSES, Job


class JobProgressResponse(BaseModel):
    current: int
    total: int | None
    percentage: float | None
    message: str | None


class JobAcceptedResponse(BaseModel):
    job_id: UUID
    status: str
    status_url: str


class JobStatusResponse(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    ready: bool
    successful: bool
    progress: JobProgressResponse
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def from_job(cls, job: Job) -> Self:
        percentage = (
            None
            if job.progress_total is None
            else round(job.progress_current / job.progress_total * 100, 2)
        )
        return cls(
            job_id=job.id,
            job_type=job.job_type,
            status=job.status,
            ready=job.status in TERMINAL_STATUSES,
            successful=job.status == SUCCESS_STATUS,
            progress=JobProgressResponse(
                current=job.progress_current,
                total=job.progress_total,
                percentage=percentage,
                message=job.progress_message,
            ),
            result=job.result,
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
```

- [ ] **Step 4: Implement durable enqueue and lookup service**

Replace `app/services/jobs.py` with:

```python
from collections.abc import Callable
import logging
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.job import Job, SEARCH_INDEX_REBUILD_JOB
from app.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)
REBUILD_PROGRESS_TOTAL = 4


class JobEnqueueError(Exception):
    pass


class JobNotFoundError(Exception):
    pass


class JobStorageError(Exception):
    pass


class TaskSender(Protocol):
    def apply_async(
        self,
        *,
        args: list[str],
        task_id: str,
    ) -> Any: ...


class JobService:
    def __init__(
        self,
        session: Session,
        rebuild_task: TaskSender,
        *,
        job_id_factory: Callable[[], UUID] = uuid4,
        repository: JobRepository | None = None,
    ) -> None:
        self.session = session
        self.rebuild_task = rebuild_task
        self.job_id_factory = job_id_factory
        self.repository = repository or JobRepository(session)

    def enqueue_search_index_rebuild(self) -> Job:
        active_job = self._get_active_rebuild()
        if active_job is not None:
            return active_job

        job_id = self.job_id_factory()
        try:
            job = self.repository.create_pending(
                job_id,
                job_type=SEARCH_INDEX_REBUILD_JOB,
                progress_total=REBUILD_PROGRESS_TOTAL,
                progress_message="Waiting for worker",
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            winning_job = self._get_active_rebuild()
            if winning_job is None:
                raise JobStorageError("Job storage unavailable.")
            return winning_job
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

        try:
            self.rebuild_task.apply_async(
                args=[str(job_id)],
                task_id=str(job_id),
            )
        except Exception as error:
            self._record_enqueue_failure(job_id)
            raise JobEnqueueError("Could not enqueue background job.") from error
        return job

    def get_job(self, job_id: UUID) -> Job:
        try:
            job = self.repository.get(job_id)
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error
        if job is None:
            raise JobNotFoundError(f"Job {job_id} was not found.")
        return job

    def _get_active_rebuild(self) -> Job | None:
        try:
            return self.repository.get_active(SEARCH_INDEX_REBUILD_JOB)
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

    def _record_enqueue_failure(self, job_id: UUID) -> None:
        try:
            self.repository.mark_failure(
                job_id,
                error="Could not enqueue background job.",
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            logger.exception("Could not persist enqueue failure for job %s.", job_id)
```

- [ ] **Step 5: Run service tests and observe GREEN**

Run:

```bash
pytest tests/unit/test_jobs.py -v
```

Expected: durable enqueue, active reuse, unique-race recovery, safe failure,
not-found, storage-error, and response-derivation tests pass.

- [ ] **Step 6: Write the failing PostgreSQL-backed API tests**

Replace `tests/integration/test_job_api.py` with:

```python
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies import get_job_service
from app.main import create_app
from app.models.job import (
    FAILURE_STATUS,
    PENDING_STATUS,
    SEARCH_INDEX_REBUILD_JOB,
    STARTED_STATUS,
    Job,
)
from app.services.jobs import (
    JobEnqueueError,
    JobNotFoundError,
    JobStorageError,
)

JOB_ID = UUID("c241dbf0-2d4e-4b91-9ad7-ce097a543bbd")


def build_job(*, status: str = PENDING_STATUS) -> Job:
    return Job(
        id=JOB_ID,
        job_type=SEARCH_INDEX_REBUILD_JOB,
        status=status,
        progress_current=2 if status == STARTED_STATUS else 0,
        progress_total=4,
        progress_message=(
            "Building search index" if status == STARTED_STATUS else "Waiting for worker"
        ),
        error="Search index rebuild failed." if status == FAILURE_STATUS else None,
        created_at=datetime(2026, 7, 21, 10, 0, tzinfo=UTC),
        started_at=(
            datetime(2026, 7, 21, 10, 1, tzinfo=UTC)
            if status == STARTED_STATUS
            else None
        ),
        updated_at=datetime(2026, 7, 21, 10, 1, tzinfo=UTC),
    )


class FakeJobService:
    def __init__(self) -> None:
        self.job = build_job()
        self.enqueue_error: Exception | None = None
        self.get_error: Exception | None = None
        self.requested_ids = []

    def enqueue_search_index_rebuild(self) -> Job:
        if self.enqueue_error:
            raise self.enqueue_error
        return self.job

    def get_job(self, job_id: UUID) -> Job:
        self.requested_ids.append(job_id)
        if self.get_error:
            raise self.get_error
        return self.job


def build_client(service: FakeJobService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_job_service] = lambda: service
    return TestClient(app)


def test_search_rebuild_returns_durable_job_id_and_status_url():
    response = build_client(FakeJobService()).post("/api/v1/search/rebuild")

    assert response.status_code == 202
    assert response.json() == {
        "job_id": str(JOB_ID),
        "status": "PENDING",
        "status_url": f"/api/v1/jobs/{JOB_ID}",
    }


def test_duplicate_rebuild_can_return_existing_started_job():
    service = FakeJobService()
    service.job = build_job(status=STARTED_STATUS)

    response = build_client(service).post("/api/v1/search/rebuild")

    assert response.status_code == 202
    assert response.json()["job_id"] == str(JOB_ID)
    assert response.json()["status"] == "STARTED"


def test_job_status_returns_postgresql_backed_progress():
    service = FakeJobService()
    service.job = build_job(status=STARTED_STATUS)

    response = build_client(service).get(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 200
    assert response.json()["job_id"] == str(JOB_ID)
    assert response.json()["progress"] == {
        "current": 2,
        "total": 4,
        "percentage": 50.0,
        "message": "Building search index",
    }
    assert service.requested_ids == [JOB_ID]


def test_unknown_job_returns_404():
    service = FakeJobService()
    service.get_error = JobNotFoundError(f"Job {JOB_ID} was not found.")

    response = build_client(service).get(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 404


def test_storage_and_broker_failures_return_safe_503():
    for error, expected in [
        (JobStorageError("Job storage unavailable."), "Job storage unavailable."),
        (
            JobEnqueueError("Could not enqueue background job."),
            "Could not enqueue background job.",
        ),
    ]:
        service = FakeJobService()
        service.enqueue_error = error
        response = build_client(service).post("/api/v1/search/rebuild")

        assert response.status_code == 503
        assert response.json()["detail"] == expected


def test_job_status_storage_failure_returns_503():
    service = FakeJobService()
    service.get_error = JobStorageError("Job storage unavailable.")

    response = build_client(service).get(f"/api/v1/jobs/{JOB_ID}")

    assert response.status_code == 503


def test_job_status_rejects_malformed_uuid():
    response = build_client(FakeJobService()).get("/api/v1/jobs/not-a-uuid")

    assert response.status_code == 422
```

- [ ] **Step 7: Run API tests and observe RED**

Run:

```bash
pytest tests/integration/test_job_api.py -v
```

Expected: collection fails because `app.api.dependencies` does not exist and the
current routes still expose `task_id` and Celery-backed status.

- [ ] **Step 8: Add the shared FastAPI service dependency**

Create `app/api/dependencies.py`:

```python
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.services.jobs import JobService
from app.workers.search_tasks import rebuild_search_index_snapshot_task


def get_job_service(
    session: Session = Depends(get_db_session),
) -> JobService:
    return JobService(session, rebuild_search_index_snapshot_task)
```

- [ ] **Step 9: Replace job-status routing with PostgreSQL lookup**

Replace `app/api/v1/jobs.py` with:

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_job_service
from app.schemas.jobs import JobStatusResponse
from app.services.jobs import JobNotFoundError, JobService, JobStorageError

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: UUID,
    service: JobService = Depends(get_job_service),
) -> JobStatusResponse:
    try:
        job = service.get_job(job_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except JobStorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JobStatusResponse.from_job(job)
```

- [ ] **Step 10: Update rebuild routing to return the durable job**

In `app/api/v1/search.py`, replace the job-related imports with:

```python
from app.api.dependencies import get_job_service
from app.schemas.jobs import JobAcceptedResponse
from app.services.jobs import (
    JobEnqueueError,
    JobService,
    JobStorageError,
)
```

Keep the existing search schema/index imports, then replace
`rebuild_search_index` with:

```python
@router.post(
    "/search/rebuild",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def rebuild_search_index(
    service: JobService = Depends(get_job_service),
) -> JobAcceptedResponse:
    try:
        job = service.enqueue_search_index_rebuild()
    except (JobEnqueueError, JobStorageError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        status_url=f"/api/v1/jobs/{job.id}",
    )
```

Remove the old `get_job_service` function and all `AsyncResult`, Celery state,
`TaskResult`, and `.delay()` logic from `app/services/jobs.py` as part of the
replacement in Step 4.

- [ ] **Step 11: Run service and API tests and observe GREEN**

Run:

```bash
pytest tests/unit/test_jobs.py tests/integration/test_job_api.py -v
pytest tests/integration/test_search_api.py -v
git diff --check
```

Expected: the new durable API contract and all unrelated search API tests pass;
`git diff --check` exits `0`.

- [ ] **Step 12: Commit and push Task 5**

```bash
git add app/schemas/jobs.py app/services/jobs.py app/api/dependencies.py app/api/v1/jobs.py app/api/v1/search.py tests/unit/test_jobs.py tests/integration/test_job_api.py
git commit -m "feat: serve durable postgresql job status"
git push origin main
```

---

### Task 6: PostgreSQL Integration, Documentation, And Live Verification

**Files:**
- Create: `tests/integration/test_job_repository_postgres.py`
- Create: `tests/integration/test_job_api_postgres.py`
- Create: `docs/job-tracking.md`
- Modify: `docs/celery-worker.md`
- Modify: `docs/db-backed-search-index.md`

**Interfaces:**
- Verifies: migration constraints and conditional transitions against PostgreSQL 16.
- Verifies: the real API service commits durable jobs and returns `404` for an unknown UUID.
- Documents: local startup, API requests, progress lifecycle, Redis restart behavior, and deferred outbox/recovery limitations.

- [ ] **Step 1: Write the live repository integration tests**

Create `tests/integration/test_job_repository_postgres.py`:

```python
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.job import (
    FAILURE_STATUS,
    SEARCH_INDEX_REBUILD_JOB,
    STARTED_STATUS,
    SUCCESS_STATUS,
    Job,
)
from app.repositories.jobs import JobRepository

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


def create_pending(repository: JobRepository, job_id=None) -> Job:
    return repository.create_pending(
        job_id or uuid4(),
        job_type=SEARCH_INDEX_REBUILD_JOB,
        progress_total=4,
        progress_message="Waiting for worker",
    )


def test_partial_unique_index_allows_only_one_active_search_rebuild(db_session):
    repository = JobRepository(db_session)
    create_pending(repository)

    with pytest.raises(IntegrityError):
        create_pending(repository)


def test_terminal_job_allows_next_rebuild_and_cannot_be_overwritten(db_session):
    repository = JobRepository(db_session)
    first = create_pending(repository)

    started = repository.claim(
        first.id,
        progress_current=1,
        progress_total=4,
        progress_message="Loading documents",
    )
    completed = repository.mark_success(
        first.id,
        result={"index_version": f"redis-{first.id}", "document_count": 3},
        progress_total=4,
        progress_message="Search index rebuilt",
    )
    rejected_failure = repository.mark_failure(
        first.id,
        error="Must not replace success.",
    )
    second = create_pending(repository)

    assert started is not None and started.status == STARTED_STATUS
    assert completed is not None and completed.status == SUCCESS_STATUS
    assert completed.result["document_count"] == 3
    assert rejected_failure is None
    assert second.id != first.id


def test_failure_is_terminal_and_stores_only_caller_supplied_safe_error(db_session):
    repository = JobRepository(db_session)
    job = create_pending(repository)

    failed = repository.mark_failure(
        job.id,
        error="Search index rebuild failed.",
    )
    rejected_claim = repository.claim(
        job.id,
        progress_current=1,
        progress_total=4,
        progress_message="Loading documents",
    )

    assert failed is not None and failed.status == FAILURE_STATUS
    assert failed.error == "Search index rebuild failed."
    assert rejected_claim is None


def test_database_rejects_progress_beyond_known_total(db_session):
    invalid = Job(
        id=uuid4(),
        job_type=SEARCH_INDEX_REBUILD_JOB,
        status="PENDING",
        progress_current=5,
        progress_total=4,
    )
    db_session.add(invalid)

    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: Write the real PostgreSQL API integration tests**

Create `tests/integration/test_job_api_postgres.py`:

```python
import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from app.api.dependencies import get_job_service
from app.core.config import get_settings
from app.main import create_app
from app.models.job import Job
from app.repositories.jobs import JobRepository
from app.services.jobs import JobService

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 to run live PostgreSQL tests",
    ),
]


class FakeTaskSender:
    def __init__(self) -> None:
        self.calls = []

    def apply_async(self, *, args: list[str], task_id: str):
        self.calls.append({"args": args, "task_id": task_id})
        return object()


@pytest.fixture
def db_session():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(Job))
    session.commit()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def client_and_task(db_session):
    task = FakeTaskSender()
    service = JobService(db_session, task)
    app = create_app()
    app.dependency_overrides[get_job_service] = lambda: service
    return TestClient(app), task, db_session


def test_rebuild_and_status_round_trip_against_postgresql(client_and_task):
    client, task, db_session = client_and_task

    accepted = client.post("/api/v1/search/rebuild")
    job_id = UUID(accepted.json()["job_id"])
    duplicate = client.post("/api/v1/search/rebuild")
    status = client.get(f"/api/v1/jobs/{job_id}")

    assert accepted.status_code == 202
    assert duplicate.status_code == 202
    assert duplicate.json()["job_id"] == str(job_id)
    assert task.calls == [{"args": [str(job_id)], "task_id": str(job_id)}]
    assert status.status_code == 200
    assert status.json()["status"] == "PENDING"
    assert JobRepository(db_session).get(job_id) is not None


def test_unknown_job_is_real_404_against_postgresql(client_and_task):
    client, _, _ = client_and_task

    response = client.get(f"/api/v1/jobs/{uuid4()}")

    assert response.status_code == 404
```

- [ ] **Step 3: Run integration tests before migration and observe RED**

With PostgreSQL running but before applying the new migration, run:

```bash
docker compose up -d postgres
RUN_POSTGRES_INTEGRATION=1 pytest tests/integration/test_job_repository_postgres.py tests/integration/test_job_api_postgres.py -v
```

Expected: tests fail with PostgreSQL `UndefinedTable` for `jobs`, proving the new
migration is required.

- [ ] **Step 4: Apply the migration and observe GREEN**

Run:

```bash
alembic upgrade head
RUN_POSTGRES_INTEGRATION=1 pytest tests/integration/test_job_repository_postgres.py tests/integration/test_job_api_postgres.py -v
```

Expected: all live job repository and API integration tests pass.

- [ ] **Step 5: Document durable job tracking**

Create `docs/job-tracking.md`:

````markdown
# Durable Job Tracking

PostgreSQL stores background-job identity, state, progress, results, and safe
errors. Redis still transports Celery messages and stores versioned search
snapshots, but job history does not depend on Redis result expiry.

## Lifecycle

```text
PENDING -> STARTED -> SUCCESS
                   -> FAILURE
PENDING ----------------> FAILURE
```

Only one search-index rebuild may be pending or running. Repeated rebuild
requests return the existing active job.

## Start The Services

```bash
docker compose up -d postgres redis
alembic upgrade head
celery -A app.workers.celery_app.celery_app worker --loglevel=info
uvicorn app.main:app --reload
```

Run the worker and API commands in separate terminals.

## Rebuild And Inspect

```bash
SEARCH_JOB_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/search/rebuild | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')
curl "http://127.0.0.1:8000/api/v1/jobs/${SEARCH_JOB_ID}"
```

Progress advances through document loading, index building, snapshot publication,
and successful completion. Unknown valid UUIDs return HTTP 404.

## Failure Safety

The API and job row contain sanitized errors. Detailed exceptions remain in the
worker or API logs. Failed rebuilds do not replace the active Redis snapshot.

PostgreSQL and Redis do not share a transaction. A process crash after committing
a pending row but before sending its Celery message can leave that row pending.
Transactional outbox dispatch and stale-job recovery are deferred until the
project needs that operational complexity.
````

In `docs/celery-worker.md` and `docs/db-backed-search-index.md`, replace every
public `task_id`, `{task_id}`, and `SEARCH_TASK_ID` reference in the rebuild flow
with `job_id`, `{job_id}`, and `SEARCH_JOB_ID`. Replace the obsolete paragraph
about unknown Celery UUIDs appearing pending with:

```markdown
PostgreSQL is the job-status source of truth. Job history survives Celery result
expiry and Redis restarts, and an unknown valid job UUID returns HTTP 404.
```

- [ ] **Step 6: Run the complete automated suite**

Run:

```bash
pytest -v
RUN_POSTGRES_INTEGRATION=1 pytest tests/integration/test_document_repository_postgres.py tests/integration/test_document_api_postgres.py tests/integration/test_search_index_api_postgres.py tests/integration/test_job_repository_postgres.py tests/integration/test_job_api_postgres.py -v
git diff --check
```

Expected: the full default suite passes with PostgreSQL tests skipped, all listed
live PostgreSQL tests pass when enabled, and `git diff --check` exits `0`.

- [ ] **Step 7: Verify the complete FastAPI, Celery, PostgreSQL, and Redis flow**

Start infrastructure and migrate:

```bash
docker compose up -d postgres redis
alembic upgrade head
docker compose ps
```

Start these long-running commands in separate terminals:

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then run:

```bash
SEARCH_JOB_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/search/rebuild | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')
python3 - "${SEARCH_JOB_ID}" <<'PY'
import json
import sys
import time
from urllib.request import urlopen

job_id = sys.argv[1]
url = f"http://127.0.0.1:8000/api/v1/jobs/{job_id}"
for _ in range(60):
    with urlopen(url) as response:
        payload = json.load(response)
    print(payload)
    if payload["status"] in {"SUCCESS", "FAILURE"}:
        if payload["status"] != "SUCCESS":
            raise SystemExit("rebuild failed")
        break
    time.sleep(0.5)
else:
    raise SystemExit("rebuild did not finish within 30 seconds")
PY
curl "http://127.0.0.1:8000/api/v1/search?q=bm25"
curl "http://127.0.0.1:8000/api/v1/jobs/00000000-0000-4000-8000-000000000000"
docker compose restart redis
curl "http://127.0.0.1:8000/api/v1/jobs/${SEARCH_JOB_ID}"
```

Expected:

- The accepted response uses one `job_id` for the API, Celery task, and
  `redis-{job_id}` index version.
- Polling reaches `SUCCESS` with progress `4/4` and a document count.
- Search reports the successfully published Redis index version.
- The unknown valid UUID returns HTTP `404`.
- The successful job remains queryable after Redis restarts.
- Worker logs contain no unexpected traceback.

- [ ] **Step 8: Commit and push Task 6**

```bash
git add tests/integration/test_job_repository_postgres.py tests/integration/test_job_api_postgres.py docs/job-tracking.md docs/celery-worker.md docs/db-backed-search-index.md
git commit -m "test: verify durable job tracking flow"
git push origin main
```

---

## Final Acceptance Check

- [ ] `GET /api/v1/jobs/{job_id}` reads PostgreSQL and returns a real `404` for unknown UUIDs.
- [ ] New and duplicate rebuild requests return the correct durable job with HTTP `202`.
- [ ] One UUID appears consistently in the API, `jobs` row, Celery task, logs, and Redis index version.
- [ ] Progress is observable as `0/4`, `1/4`, `2/4`, `3/4`, and `4/4` at the designed stages.
- [ ] Conditional updates protect terminal states and duplicate Celery delivery.
- [ ] Broker, database, index-build, and Redis-publication failures expose only safe public messages.
- [ ] A failed rebuild leaves the previous active search snapshot unchanged.
- [ ] The default suite, live PostgreSQL suite, and complete service flow pass.
- [ ] Every task commit is present on `origin/main` and the worktree is clean.
