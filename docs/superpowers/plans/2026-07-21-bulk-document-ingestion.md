# Bulk Document Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build durable asynchronous ingestion for 1 to 500 JSON documents with partial success, PostgreSQL item tracking, one final search-index publication, and inspectable job progress.

**Architecture:** FastAPI stages a durable job and raw ingestion items in one PostgreSQL transaction, then sends only the shared job UUID to Celery. A worker validates and imports each pending item independently, persists outcomes, and publishes one versioned Redis snapshot when data changed. A shared job resource key serializes background snapshot publishers, while task-specific advisory locking and idempotent item transitions make retries safe.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.x, PostgreSQL 16, Alembic, Celery, Redis 7, pytest

**Design:** `docs/superpowers/specs/2026-07-21-bulk-document-ingestion-design.md`

## Global Constraints

- Accept JSON only; file, CSV, and NDJSON uploads are outside this milestone.
- Accept 1 to 500 entries per request.
- Reject only malformed envelopes synchronously; validate individual entries in the worker.
- Import valid entries even when siblings are invalid or duplicate.
- Treat only repeated non-null URLs as duplicates; URL-less documents remain valid.
- Store raw item payloads and safe outcomes in PostgreSQL; never place document content in a Celery message.
- Use one UUID for the public job id, PostgreSQL job id, and Celery task id.
- Allow only one active background job with `resource_key="search_index"`.
- Return HTTP `409` for a bulk request blocked by an active index job.
- Rebuild and publish at most one new index version per successfully changed batch.
- Retry transient PostgreSQL and Redis failures at most three times; do not retry item validation failures.
- Keep raw exception details in logs and expose only stable safe messages.
- Preserve all existing document, search, snapshot, and durable-job behavior.
- Commit and push every completed task to `main` after its focused tests pass.

## File Map

Create:

- `app/models/ingestion_item.py`: staged payload and durable item-outcome model.
- `app/repositories/ingestion_items.py`: staging, locking, transitions, counts, and pagination.
- `app/schemas/bulk_ingestion.py`: request, internal validation, conflict, and item-report schemas.
- `app/services/document_ingestion.py`: one-item validation and transactional import.
- `app/services/bulk_ingestion.py`: API-facing stage, enqueue, and report orchestration.
- `app/services/bulk_ingestion_runner.py`: worker-facing progress, summary, and index rebuild orchestration.
- `app/services/advisory_locks.py`: PostgreSQL advisory lock for duplicate task delivery.
- `app/workers/ingestion_tasks.py`: bound Celery task and bounded retry policy.
- `alembic/versions/20260721_0003_create_bulk_ingestion.py`: resource-key and ingestion-item migration.
- `tests/unit/test_ingestion_item_model.py`: model metadata and SQL compilation tests.
- `tests/unit/test_bulk_ingestion_schemas.py`: envelope and item validation tests.
- `tests/unit/test_ingestion_item_repository.py`: repository statement and transition tests.
- `tests/unit/test_document_ingestion.py`: one-item processor tests.
- `tests/unit/test_bulk_ingestion.py`: stage/enqueue/report service tests.
- `tests/unit/test_bulk_ingestion_runner.py`: worker orchestration tests.
- `tests/unit/test_worker_ingestion_tasks.py`: lock, retry, redelivery, and task configuration tests.
- `tests/integration/test_bulk_ingestion_api.py`: FastAPI contract tests with a fake service.
- `tests/integration/test_bulk_ingestion_postgres.py`: live PostgreSQL repository and service tests.
- `tests/integration/test_bulk_ingestion_e2e.py`: live PostgreSQL, Redis, task, snapshot, and search flow.
- `docs/bulk-ingestion.md`: local usage and operational behavior.

Modify:

- `app/models/job.py`: job type, shared resource key, and partial unique index.
- `app/models/__init__.py`: export model names.
- `alembic/env.py`: register the ingestion model with Alembic metadata.
- `app/repositories/jobs.py`: resource lookup and resource-aware creation.
- `app/services/jobs.py`: resource-aware rebuild deduplication and conflict error.
- `app/services/job_tracker.py`: durable reads and retry-safe resume support.
- `app/api/dependencies.py`: construct the bulk service with a named Celery
  signature.
- `app/api/v1/documents.py`: bulk submit and item-report routes before dynamic id routes.
- `app/api/v1/search.py`: map cross-type index-job conflicts to HTTP `409`.
- `app/workers/celery_app.py`: register the ingestion task module.
- Existing model, repository, service, API, worker, and PostgreSQL tests: preserve and extend contracts.
- `docs/job-tracking.md`: shared resource and bulk lifecycle.
- `docs/celery-worker.md`: bulk task commands.

---

### Task 1: Add The Bulk-Ingestion Database Schema

**Files:**
- Create: `app/models/ingestion_item.py`
- Create: `alembic/versions/20260721_0003_create_bulk_ingestion.py`
- Create: `tests/unit/test_ingestion_item_model.py`
- Modify: `app/models/job.py`
- Modify: `app/models/__init__.py`
- Modify: `alembic/env.py`
- Modify: `tests/unit/test_job_model.py`

**Interfaces:**
- Produces: `BULK_DOCUMENT_INGESTION_JOB`, `SEARCH_INDEX_RESOURCE`, item-status constants, `Job.resource_key`, and `IngestionItem`.
- Consumes: existing `Base`, `Job`, and `Document` tables.

- [ ] **Step 1: Write failing model tests**

Add assertions to `tests/unit/test_job_model.py` for `resource_key` and `jobs_one_active_resource_idx`. Create `tests/unit/test_ingestion_item_model.py` with these core checks:

```python
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.document import Document
from app.models.ingestion_item import IngestionItem
from app.models.job import Job


def test_ingestion_item_model_has_durable_payload_outcome_columns():
    assert IngestionItem.__tablename__ == "ingestion_items"
    assert {
        "id", "job_id", "position", "payload", "status",
        "document_id", "error", "created_at", "updated_at",
    } == set(IngestionItem.__table__.columns.keys())


def test_ingestion_item_model_declares_constraints_and_indexes():
    constraint_names = {
        constraint.name for constraint in IngestionItem.__table__.constraints
    }
    index_names = {index.name for index in IngestionItem.__table__.indexes}
    assert "ingestion_items_job_position_key" in constraint_names
    assert "ingestion_items_position_check" in constraint_names
    assert "ingestion_items_status_check" in constraint_names
    assert "ingestion_items_outcome_check" in constraint_names
    assert "ingestion_items_job_status_position_idx" in index_names


def test_ingestion_item_model_compiles_postgresql_jsonb_and_foreign_keys():
    sql = str(CreateTable(IngestionItem.__table__).compile(
        dialect=postgresql.dialect()
    ))
    assert "CREATE TABLE ingestion_items" in sql
    assert "JSONB NOT NULL" in sql
    assert "FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE" in sql
    assert "FOREIGN KEY(document_id) REFERENCES documents (id)" in sql
```

- [ ] **Step 2: Run the tests and confirm the schema is missing**

Run:

```bash
python3 -m pytest tests/unit/test_job_model.py tests/unit/test_ingestion_item_model.py -q
```

Expected: collection fails because `app.models.ingestion_item` does not exist, or assertions fail because `resource_key` is absent.

- [ ] **Step 3: Implement the SQLAlchemy models**

In `app/models/job.py`, add:

```python
BULK_DOCUMENT_INGESTION_JOB = "bulk_document_ingestion"
SEARCH_INDEX_RESOURCE = "search_index"

resource_key: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Replace `jobs_one_active_search_index_rebuild_idx` with:

```python
Index(
    "jobs_one_active_resource_idx",
    "resource_key",
    unique=True,
    postgresql_where=text(
        "resource_key is not null "
        "and status in ('PENDING', 'STARTED')"
    ),
)
```

Create `app/models/ingestion_item.py` with these lowercase item-status constants:

```python
PENDING_ITEM_STATUS = "pending"
IMPORTED_ITEM_STATUS = "imported"
SKIPPED_ITEM_STATUS = "skipped"
FAILED_ITEM_STATUS = "failed"
TERMINAL_ITEM_STATUSES = (
    IMPORTED_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    FAILED_ITEM_STATUS,
)
```

Use this model contract:

```python
class IngestionItem(Base):
    __tablename__ = "ingestion_items"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "position", name="ingestion_items_job_position_key"
        ),
        CheckConstraint(
            "position >= 0", name="ingestion_items_position_check"
        ),
        CheckConstraint(
            "status in ('pending', 'imported', 'skipped', 'failed')",
            name="ingestion_items_status_check",
        ),
        CheckConstraint(
            "(status = 'pending' and document_id is null and error is null) or "
            "(status = 'imported' and document_id is not null and error is null) or "
            "(status in ('skipped', 'failed') and document_id is null and error is not null)",
            name="ingestion_items_outcome_check",
        ),
        Index(
            "ingestion_items_job_status_position_idx",
            "job_id", "status", "position",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
    )
    document_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("documents.id"),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now()
    )
```

Export `Document`, `IngestionItem`, and `Job` from `app/models/__init__.py`, and import `IngestionItem` in `alembic/env.py` so Alembic sees the table.

- [ ] **Step 4: Add migration `20260721_0003`**

The migration must perform these operations in order:

```python
op.add_column("jobs", sa.Column("resource_key", sa.Text(), nullable=True))
op.execute(
    "update jobs set resource_key = 'search_index' "
    "where job_type = 'search_index_rebuild'"
)
op.drop_index("jobs_one_active_search_index_rebuild_idx", table_name="jobs")
op.create_index(
    "jobs_one_active_resource_idx",
    "jobs",
    ["resource_key"],
    unique=True,
    postgresql_where=sa.text(
        "resource_key is not null and status in ('PENDING', 'STARTED')"
    ),
)
```

Create the item table and index with:

```python
op.create_table(
    "ingestion_items",
    sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
    sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("position", sa.Integer(), nullable=False),
    sa.Column(
        "payload",
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    ),
    sa.Column("status", sa.Text(), server_default="pending", nullable=False),
    sa.Column("document_id", sa.BigInteger(), nullable=True),
    sa.Column("error", sa.Text(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.CheckConstraint(
        "position >= 0", name="ingestion_items_position_check"
    ),
    sa.CheckConstraint(
        "status in ('pending', 'imported', 'skipped', 'failed')",
        name="ingestion_items_status_check",
    ),
    sa.CheckConstraint(
        "(status = 'pending' and document_id is null and error is null) or "
        "(status = 'imported' and document_id is not null and error is null) or "
        "(status in ('skipped', 'failed') and document_id is null and error is not null)",
        name="ingestion_items_outcome_check",
    ),
    sa.ForeignKeyConstraint(
        ["job_id"], ["jobs.id"], ondelete="CASCADE"
    ),
    sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
    sa.PrimaryKeyConstraint("id"),
    sa.UniqueConstraint(
        "job_id", "position", name="ingestion_items_job_position_key"
    ),
)
op.create_index(
    "ingestion_items_job_status_position_idx",
    "ingestion_items",
    ["job_id", "status", "position"],
)
```

The downgrade order is:

```python
op.drop_index(
    "ingestion_items_job_status_position_idx",
    table_name="ingestion_items",
)
op.drop_table("ingestion_items")
op.drop_index("jobs_one_active_resource_idx", table_name="jobs")
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
op.drop_column("jobs", "resource_key")
```

- [ ] **Step 5: Run focused tests and migration**

Run:

```bash
python3 -m pytest tests/unit/test_job_model.py tests/unit/test_ingestion_item_model.py -q
alembic upgrade head
alembic current
alembic downgrade 20260721_0002
alembic upgrade head
alembic current
```

Expected: tests pass, downgrade returns to `20260721_0002`, re-upgrade succeeds,
and the final current revision is `20260721_0003 (head)`.

- [ ] **Step 6: Commit and push**

```bash
git add app/models alembic/env.py alembic/versions/20260721_0003_create_bulk_ingestion.py tests/unit/test_job_model.py tests/unit/test_ingestion_item_model.py
git commit -m "feat: add bulk ingestion database schema"
git push origin main
```

### Task 2: Serialize Background Search-Index Jobs

**Files:**
- Modify: `app/repositories/jobs.py`
- Modify: `app/services/jobs.py`
- Modify: `app/api/v1/search.py`
- Modify: `tests/unit/test_job_repository.py`
- Modify: `tests/unit/test_jobs.py`
- Modify: `tests/integration/test_job_api.py`
- Modify: `tests/integration/test_job_repository_postgres.py`

**Interfaces:**
- Produces: `JobRepository.get_active_by_type()`, `JobRepository.get_active_by_resource()`, and `IndexJobConflictError.active_job`.
- Consumes: `SEARCH_INDEX_RESOURCE` and existing rebuild task sender.

- [ ] **Step 1: Write failing resource-concurrency tests**

Cover all four rules:

```python
def test_create_pending_records_optional_resource_key():
    job = repository.create_pending(
        JOB_ID,
        job_type=SEARCH_INDEX_REBUILD_JOB,
        resource_key=SEARCH_INDEX_RESOURCE,
        progress_total=4,
        progress_message="Waiting for worker",
    )
    assert job.resource_key == SEARCH_INDEX_RESOURCE


def test_get_active_by_resource_filters_pending_and_started_jobs():
    job = repository.get_active_by_resource(SEARCH_INDEX_RESOURCE)
    assert job is expected


def test_rebuild_reuses_an_active_rebuild_for_the_resource():
    repository.active_resource = build_job(status=STARTED_STATUS)
    assert service.enqueue_search_index_rebuild() is repository.active_resource


def test_rebuild_conflicts_with_an_active_bulk_job():
    repository.active_resource = build_job(
        status=STARTED_STATUS,
        job_type=BULK_DOCUMENT_INGESTION_JOB,
    )
    with pytest.raises(IndexJobConflictError) as caught:
        service.enqueue_search_index_rebuild()
    assert caught.value.active_job is repository.active_resource
```

Add a PostgreSQL test that creates active rebuild and bulk jobs with the same
resource and expects the second flush to raise `IntegrityError`.

- [ ] **Step 2: Run the focused tests and observe failure**

```bash
python3 -m pytest tests/unit/test_job_repository.py tests/unit/test_jobs.py tests/integration/test_job_api.py -q
```

Expected: failures for missing resource-aware methods and conflict behavior.

- [ ] **Step 3: Implement resource-aware repository and service behavior**

Change `create_pending` to accept and store `resource_key: str | None = None`.
Rename the current type lookup to `get_active_by_type(job_type: str)` and add:

```python
def get_active_by_resource(self, resource_key: str) -> Job | None:
    statement = select(Job).where(
        Job.resource_key == resource_key,
        Job.status.in_(ACTIVE_STATUSES),
    )
    return self.session.scalars(statement).one_or_none()
```

Add this service error:

```python
class IndexJobConflictError(Exception):
    def __init__(self, active_job: Job) -> None:
        super().__init__("A search index job is already active.")
        self.active_job = active_job
```

`enqueue_search_index_rebuild()` must look up `SEARCH_INDEX_RESOURCE`. Return the
active job only when its type is `SEARCH_INDEX_REBUILD_JOB`; otherwise raise
`IndexJobConflictError`. New rebuild rows must store `resource_key`.

After a unique-index race, roll back, load the active resource owner, and apply
the same same-type reuse or cross-type conflict rule.

- [ ] **Step 4: Map rebuild conflicts to HTTP `409`**

In `app/api/v1/search.py`, catch `IndexJobConflictError` and return:

```python
raise HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={
        "message": str(error),
        "active_job_id": str(error.active_job.id),
        "status_url": f"/api/v1/jobs/{error.active_job.id}",
    },
) from error
```

Add an API test asserting the exact safe response and that no task is sent.

- [ ] **Step 5: Run unit, API, and live PostgreSQL tests**

```bash
python3 -m pytest tests/unit/test_job_repository.py tests/unit/test_jobs.py tests/integration/test_job_api.py -q
RUN_POSTGRES_INTEGRATION=1 python3 -m pytest tests/integration/test_job_repository_postgres.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit and push**

```bash
git add app/models/job.py app/repositories/jobs.py app/services/jobs.py app/api/v1/search.py tests/unit/test_job_repository.py tests/unit/test_jobs.py tests/integration/test_job_api.py tests/integration/test_job_repository_postgres.py
git commit -m "feat: serialize search index jobs"
git push origin main
```

### Task 3: Define Bulk Request And Report Contracts

**Files:**
- Create: `app/schemas/bulk_ingestion.py`
- Create: `tests/unit/test_bulk_ingestion_schemas.py`

**Interfaces:**
- Produces: `BulkDocumentsRequest`, `BulkDocumentInput`, `format_item_validation_error()`, `IngestionItemResponse`, and `IngestionItemListResponse`.
- Consumes: Pydantic `JsonValue` and `IngestionItem`.

- [ ] **Step 1: Write failing schema tests**

```python
import pytest
from pydantic import ValidationError

from app.schemas.bulk_ingestion import (
    BulkDocumentInput,
    BulkDocumentsRequest,
    format_item_validation_error,
)


def test_envelope_accepts_raw_json_values_for_partial_worker_validation():
    payload = BulkDocumentsRequest.model_validate({
        "documents": [
            {"title": "Valid", "content": "Search content"},
            {"title": "Missing content"},
            42,
        ]
    })
    assert len(payload.documents) == 3


@pytest.mark.parametrize("documents", [[], [{}] * 501])
def test_envelope_enforces_batch_size(documents):
    with pytest.raises(ValidationError):
        BulkDocumentsRequest.model_validate({"documents": documents})


def test_item_validation_strips_text_and_blank_url():
    item = BulkDocumentInput.model_validate({
        "title": "  BM25  ",
        "content": "  ranking content  ",
        "url": "  ",
    })
    assert item.model_dump() == {
        "title": "BM25", "content": "ranking content", "url": None
    }


def test_item_validation_rejects_extra_fields_with_safe_reason():
    with pytest.raises(ValidationError) as caught:
        BulkDocumentInput.model_validate({
            "title": "BM25", "content": "Ranking", "secret": "value"
        })
    reason = format_item_validation_error(caught.value)
    assert reason == "secret: Extra inputs are not permitted"
```

- [ ] **Step 2: Run the tests and confirm the module is missing**

```bash
python3 -m pytest tests/unit/test_bulk_ingestion_schemas.py -q
```

Expected: collection fails because `app.schemas.bulk_ingestion` does not exist.

- [ ] **Step 3: Implement strict item validation and response schemas**

Implement:

```python
class BulkDocumentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: list[JsonValue] = Field(min_length=1, max_length=500)


class BulkDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str
    content: str
    url: str | None = None

    @field_validator("title", "content")
    @classmethod
    def strip_non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must be a non-empty string")
        return stripped

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None
```

Add deterministic safe error formatting and report models:

```python
def format_item_validation_error(error: ValidationError) -> str:
    first = error.errors(include_url=False, include_context=False)[0]
    location = ".".join(str(part) for part in first["loc"]) or "item"
    message = str(first["msg"]).removeprefix("Value error, ")
    return f"{location}: {message}"[:300]


class IngestionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    status: str
    document_id: int | None
    error: str | None


class IngestionItemListResponse(BaseModel):
    job_id: UUID
    total_results: int
    limit: int
    offset: int
    items: list[IngestionItemResponse]
```

- [ ] **Step 4: Run the schema tests**

```bash
python3 -m pytest tests/unit/test_bulk_ingestion_schemas.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit and push**

```bash
git add app/schemas/bulk_ingestion.py tests/unit/test_bulk_ingestion_schemas.py
git commit -m "feat: define bulk ingestion contracts"
git push origin main
```

### Task 4: Add The Ingestion-Item Repository

**Files:**
- Create: `app/repositories/ingestion_items.py`
- Create: `tests/unit/test_ingestion_item_repository.py`
- Create: `tests/integration/test_bulk_ingestion_postgres.py`

**Interfaces:**
- Produces: `IngestionCounts`, `stage_many()`, `get_for_update()`, `list_pending_ids()`, guarded outcome methods, `counts()`, `count_for_job()`, and `list_for_job()`.
- Consumes: `IngestionItem` and item-status constants.

- [ ] **Step 1: Write failing repository tests**

Test object creation and compile every query against the PostgreSQL dialect:

```python
def test_stage_many_preserves_zero_based_positions_and_raw_payloads():
    items = repository.stage_many(JOB_ID, [{"title": "One"}, 42])
    assert [(item.position, item.payload) for item in items] == [
        (0, {"title": "One"}), (1, 42)
    ]
    assert all(item.status == PENDING_ITEM_STATUS for item in items)


def test_outcome_updates_are_guarded_by_pending_status():
    repository.mark_imported(10, document_id=90)
    repository.mark_skipped(11, error="duplicate_url")
    repository.mark_failed(12, error="content: Field required")
    for statement in session.statements:
        sql = compile_sql(statement)
        assert "status = 'pending'" in sql


def test_pending_ids_and_reports_use_stable_position_order():
    repository.list_pending_ids(JOB_ID)
    repository.list_for_job(JOB_ID, limit=25, offset=50)
    assert all("ORDER BY ingestion_items.position ASC" in compile_sql(statement)
               for statement in session.statements)
```

Add live PostgreSQL tests for constraints, outcome transitions, ordering, and
count grouping under the existing `RUN_POSTGRES_INTEGRATION=1` marker.

- [ ] **Step 2: Run the focused tests and observe failure**

```bash
python3 -m pytest tests/unit/test_ingestion_item_repository.py -q
```

Expected: collection fails because the repository module does not exist.

- [ ] **Step 3: Implement repository operations**

Define:

```python
@dataclass(frozen=True)
class IngestionCounts:
    received: int
    imported: int
    skipped: int
    failed: int


class IngestionItemRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def stage_many(self, job_id: UUID, payloads: list[JsonValue]) -> list[IngestionItem]:
        items = [
            IngestionItem(job_id=job_id, position=position, payload=payload)
            for position, payload in enumerate(payloads)
        ]
        self.session.add_all(items)
        self.session.flush()
        return items
```

Add these query methods, using a private `_mark()` helper for all outcomes:

```python
def get_for_update(self, item_id: int) -> IngestionItem | None:
    statement = (
        select(IngestionItem)
        .where(IngestionItem.id == item_id)
        .with_for_update()
    )
    return self.session.scalars(statement).one_or_none()

def list_pending_ids(self, job_id: UUID) -> list[int]:
    statement = (
        select(IngestionItem.id)
        .where(
            IngestionItem.job_id == job_id,
            IngestionItem.status == PENDING_ITEM_STATUS,
        )
        .order_by(IngestionItem.position.asc())
    )
    return list(self.session.scalars(statement).all())

def mark_imported(self, item_id: int, *, document_id: int) -> IngestionItem | None:
    return self._mark(
        item_id,
        status=IMPORTED_ITEM_STATUS,
        document_id=document_id,
        error=None,
    )

def mark_skipped(self, item_id: int, *, error: str) -> IngestionItem | None:
    return self._mark(
        item_id,
        status=SKIPPED_ITEM_STATUS,
        document_id=None,
        error=error,
    )

def mark_failed(self, item_id: int, *, error: str) -> IngestionItem | None:
    return self._mark(
        item_id,
        status=FAILED_ITEM_STATUS,
        document_id=None,
        error=error,
    )

def _mark(
    self,
    item_id: int,
    *,
    status: str,
    document_id: int | None,
    error: str | None,
) -> IngestionItem | None:
    statement = (
        update(IngestionItem)
        .where(
            IngestionItem.id == item_id,
            IngestionItem.status == PENDING_ITEM_STATUS,
        )
        .values(
            status=status,
            document_id=document_id,
            error=error,
            updated_at=func.now(),
        )
        .returning(IngestionItem)
    )
    return self.session.scalars(statement).one_or_none()
```

Add count and pagination methods:

```python
def count_terminal(self, job_id: UUID) -> int:
    statement = (
        select(func.count())
        .select_from(IngestionItem)
        .where(
            IngestionItem.job_id == job_id,
            IngestionItem.status.in_(TERMINAL_ITEM_STATUSES),
        )
    )
    return int(self.session.scalar(statement) or 0)

def counts(self, job_id: UUID) -> IngestionCounts:
    statement = (
        select(IngestionItem.status, func.count(IngestionItem.id))
        .where(IngestionItem.job_id == job_id)
        .group_by(IngestionItem.status)
    )
    grouped = dict(self.session.execute(statement).all())
    return IngestionCounts(
        received=sum(grouped.values()),
        imported=grouped.get(IMPORTED_ITEM_STATUS, 0),
        skipped=grouped.get(SKIPPED_ITEM_STATUS, 0),
        failed=grouped.get(FAILED_ITEM_STATUS, 0),
    )

def count_for_job(self, job_id: UUID) -> int:
    statement = (
        select(func.count())
        .select_from(IngestionItem)
        .where(IngestionItem.job_id == job_id)
    )
    return int(self.session.scalar(statement) or 0)

def list_for_job(
    self,
    job_id: UUID,
    *,
    limit: int,
    offset: int,
) -> list[IngestionItem]:
    if limit < 1:
        raise ValueError("limit must be at least 1.")
    if offset < 0:
        raise ValueError("offset cannot be negative.")
    statement = (
        select(IngestionItem)
        .where(IngestionItem.job_id == job_id)
        .order_by(IngestionItem.position.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(self.session.scalars(statement).all())
```

- [ ] **Step 4: Run unit and PostgreSQL repository tests**

```bash
python3 -m pytest tests/unit/test_ingestion_item_repository.py -q
RUN_POSTGRES_INTEGRATION=1 python3 -m pytest tests/integration/test_bulk_ingestion_postgres.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit and push**

```bash
git add app/repositories/ingestion_items.py tests/unit/test_ingestion_item_repository.py tests/integration/test_bulk_ingestion_postgres.py
git commit -m "feat: add ingestion item repository"
git push origin main
```

### Task 5: Process One Staged Document Transactionally

**Files:**
- Create: `app/services/document_ingestion.py`
- Create: `tests/unit/test_document_ingestion.py`
- Modify: `tests/integration/test_bulk_ingestion_postgres.py`

**Interfaces:**
- Produces: `IngestionItemProcessor.process(item_id: int) -> IngestionOutcome`, `IngestionOutcome`, and `IngestionItemNotFoundError`.
- Consumes: `BulkDocumentInput`, `DocumentRepository`, and `IngestionItemRepository`.

- [ ] **Step 1: Write failing processor tests**

Cover these outcomes with injected session/repository factories:

```python
def test_valid_item_creates_document_and_marks_imported():
    outcome = processor.process(ITEM_ID)
    assert outcome.status == IMPORTED_ITEM_STATUS
    assert outcome.document_id == 81
    assert item_repository.imported_with == {
        "item_id": ITEM_ID, "document_id": 81
    }
    assert session.commits == 1
    assert session.closed is True


def test_invalid_item_is_failed_without_inserting_document():
    item.payload = {"title": "Missing content"}
    outcome = processor.process(ITEM_ID)
    assert outcome.status == FAILED_ITEM_STATUS
    assert outcome.error == "content: Field required"
    assert document_repository.created_with is None


def test_named_url_unique_violation_is_skipped():
    document_repository.error = duplicate_url_integrity_error()
    outcome = processor.process(ITEM_ID)
    assert outcome.status == SKIPPED_ITEM_STATUS
    assert outcome.error == "duplicate_url"


def test_terminal_item_is_returned_without_writing_again():
    item.status = IMPORTED_ITEM_STATUS
    item.document_id = 81
    outcome = processor.process(ITEM_ID)
    assert outcome.document_id == 81
    assert document_repository.created_with is None
```

Also test URL-less input, unknown item id, rollback on operational failure, and
safe classification of a non-URL integrity error.

- [ ] **Step 2: Run the tests and confirm failure**

```bash
python3 -m pytest tests/unit/test_document_ingestion.py -q
```

Expected: collection fails because `app.services.document_ingestion` is missing.

- [ ] **Step 3: Implement the processor**

Define:

```python
@dataclass(frozen=True)
class IngestionOutcome:
    position: int
    status: str
    document_id: int | None
    error: str | None

    @classmethod
    def from_item(cls, item: IngestionItem) -> "IngestionOutcome":
        return cls(
            position=item.position,
            status=item.status,
            document_id=item.document_id,
            error=item.error,
        )


class IngestionItemNotFoundError(Exception):
    pass
```

`IngestionItemProcessor` accepts these injectable factories:

```python
class IngestionItemProcessor:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        item_repository_factory: Callable[
            [Session], IngestionItemRepository
        ] = IngestionItemRepository,
        document_repository_factory: Callable[
            [Session], DocumentRepository
        ] = DocumentRepository,
    ) -> None:
        self.session_factory = session_factory
        self.item_repository_factory = item_repository_factory
        self.document_repository_factory = document_repository_factory
```

Use this transaction sequence in `process(item_id)`:

```python
session = self.session_factory()
try:
    items = self.item_repository_factory(session)
    item = items.get_for_update(item_id)
    if item is None:
        raise IngestionItemNotFoundError(f"Ingestion item {item_id} was not found.")
    if item.status != PENDING_ITEM_STATUS:
        return IngestionOutcome.from_item(item)

    try:
        payload = BulkDocumentInput.model_validate(item.payload)
    except ValidationError as error:
        updated = items.mark_failed(
            item.id, error=format_item_validation_error(error)
        )
    else:
        try:
            with session.begin_nested():
                document = self.document_repository_factory(session).create(
                    title=payload.title,
                    content=payload.content,
                    url=payload.url,
                )
        except IntegrityError as error:
            if constraint_name(error) == "documents_url_key":
                updated = items.mark_skipped(item.id, error="duplicate_url")
            else:
                updated = items.mark_failed(item.id, error="document_integrity_error")
        else:
            updated = items.mark_imported(item.id, document_id=document.id)

    if updated is None:
        raise RuntimeError("Pending ingestion item rejected its outcome.")
    session.commit()
    return IngestionOutcome.from_item(updated)
except Exception:
    session.rollback()
    raise
finally:
    session.close()
```

Read the named PostgreSQL constraint without including raw exception text in the
outcome:

```python
def constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return name if isinstance(name, str) else None
```

- [ ] **Step 4: Run processor and live PostgreSQL tests**

```bash
python3 -m pytest tests/unit/test_document_ingestion.py -q
RUN_POSTGRES_INTEGRATION=1 python3 -m pytest tests/integration/test_bulk_ingestion_postgres.py -q
```

Expected: valid, invalid, duplicate, and URL-less cases pass.

- [ ] **Step 5: Commit and push**

```bash
git add app/services/document_ingestion.py tests/unit/test_document_ingestion.py tests/integration/test_bulk_ingestion_postgres.py
git commit -m "feat: process staged ingestion items"
git push origin main
```

### Task 6: Stage, Enqueue, And Report Bulk Jobs

**Files:**
- Create: `app/services/bulk_ingestion.py`
- Create: `tests/unit/test_bulk_ingestion.py`

**Interfaces:**
- Produces: `BulkIngestionService.enqueue_documents()`, `list_items()`, `BulkIngestionNotFoundError`, and uses existing safe job storage/enqueue errors.
- Consumes: job resource coordination, ingestion-item repository, and a Celery-compatible task sender.

- [ ] **Step 1: Write failing service tests**

```python
def test_enqueue_commits_job_and_items_before_sending_only_job_id():
    job = service.enqueue_documents([VALID_PAYLOAD, INVALID_PAYLOAD])
    assert session.commits == 1
    assert jobs.created_with == {
        "job_id": JOB_ID,
        "job_type": BULK_DOCUMENT_INGESTION_JOB,
        "resource_key": SEARCH_INDEX_RESOURCE,
        "progress_total": 3,
        "progress_message": "Waiting for worker",
    }
    assert items.staged_with == {
        "job_id": JOB_ID,
        "payloads": [VALID_PAYLOAD, INVALID_PAYLOAD],
    }
    assert task.calls == [{"args": [str(JOB_ID)], "task_id": str(JOB_ID)}]


def test_active_resource_rejects_new_batch_without_staging():
    jobs.active_resource = active_job
    with pytest.raises(IndexJobConflictError) as caught:
        service.enqueue_documents([VALID_PAYLOAD])
    assert caught.value.active_job is active_job
    assert items.staged_with is None
    assert task.calls == []


def test_broker_failure_marks_job_failed_with_safe_message():
    task.error = ConnectionError("redis password leaked")
    with pytest.raises(JobEnqueueError):
        service.enqueue_documents([VALID_PAYLOAD])
    assert jobs.failed_with["error"] == "Could not enqueue background job."


def test_list_items_rejects_unknown_or_non_bulk_job():
    jobs.job = rebuild_job
    with pytest.raises(BulkIngestionNotFoundError):
        service.list_items(JOB_ID, limit=100, offset=0)
```

Also test unique-resource race recovery, database-error mapping, total count, and
stable paginated item ordering.

- [ ] **Step 2: Run tests and confirm failure**

```bash
python3 -m pytest tests/unit/test_bulk_ingestion.py -q
```

Expected: collection fails because the service module is missing.

- [ ] **Step 3: Implement the API-facing service**

The constructor accepts `Session`, task sender, UUID factory, `JobRepository`, and
`IngestionItemRepository`. Implement:

```python
def enqueue_documents(self, payloads: list[JsonValue]) -> Job:
    active_job = self._get_active_index_job()
    if active_job is not None:
        raise IndexJobConflictError(active_job)

    job_id = self.job_id_factory()
    try:
        job = self.jobs.create_pending(
            job_id,
            job_type=BULK_DOCUMENT_INGESTION_JOB,
            resource_key=SEARCH_INDEX_RESOURCE,
            progress_total=len(payloads) + 1,
            progress_message="Waiting for worker",
        )
        self.items.stage_many(job_id, payloads)
        self.session.commit()
    except IntegrityError:
        self.session.rollback()
        winner = self._get_active_index_job()
        if winner is None:
            raise JobStorageError("Job storage unavailable.")
        raise IndexJobConflictError(winner)
    except SQLAlchemyError as error:
        self.session.rollback()
        raise JobStorageError("Job storage unavailable.") from error

    try:
        self.task.apply_async(args=[str(job_id)], task_id=str(job_id))
    except Exception as error:
        self._record_enqueue_failure(job_id)
        raise JobEnqueueError("Could not enqueue background job.") from error
    return job
```

Add the report lookup and not-found error:

```python
class BulkIngestionNotFoundError(Exception):
    pass


def list_items(
    self,
    job_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[int, list[IngestionItem]]:
    try:
        job = self.jobs.get(job_id)
        if job is None or job.job_type != BULK_DOCUMENT_INGESTION_JOB:
            raise BulkIngestionNotFoundError(
                f"Bulk ingestion job {job_id} was not found."
            )
        total = self.items.count_for_job(job_id)
        items = self.items.list_for_job(
            job_id, limit=limit, offset=offset
        )
        return total, items
    except BulkIngestionNotFoundError:
        raise
    except SQLAlchemyError as error:
        self.session.rollback()
        raise JobStorageError("Job storage unavailable.") from error
```

Use these helpers so storage and broker failures remain safe:

```python
def _get_active_index_job(self) -> Job | None:
    try:
        return self.jobs.get_active_by_resource(SEARCH_INDEX_RESOURCE)
    except SQLAlchemyError as error:
        self.session.rollback()
        raise JobStorageError("Job storage unavailable.") from error

def _record_enqueue_failure(self, job_id: UUID) -> None:
    try:
        self.jobs.mark_failure(
            job_id, error="Could not enqueue background job."
        )
        self.session.commit()
    except SQLAlchemyError:
        self.session.rollback()
        logger.exception(
            "Could not persist enqueue failure for job %s.", job_id
        )
```

- [ ] **Step 4: Run service tests**

```bash
python3 -m pytest tests/unit/test_bulk_ingestion.py tests/unit/test_jobs.py -q
```

Expected: all tests pass and existing rebuild behavior remains green.

- [ ] **Step 5: Commit and push**

```bash
git add app/services/bulk_ingestion.py tests/unit/test_bulk_ingestion.py
git commit -m "feat: enqueue durable bulk ingestion jobs"
git push origin main
```

### Task 7: Expose Bulk Ingestion Through FastAPI

**Files:**
- Create: `tests/integration/test_bulk_ingestion_api.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/api/v1/documents.py`

**Interfaces:**
- Produces: `POST /api/v1/documents/bulk` and `GET /api/v1/documents/bulk/{job_id}/items`.
- Consumes: `BulkIngestionService`, bulk schemas, and `JobAcceptedResponse`.

- [ ] **Step 1: Write failing API contract tests**

Use a fake bulk service dependency and assert:

```python
def test_bulk_submit_returns_202_job_contract(client):
    response = client.post("/api/v1/documents/bulk", json={
        "documents": [VALID_PAYLOAD, {"title": "Missing content"}]
    })
    assert response.status_code == 202
    assert response.json() == {
        "job_id": str(JOB_ID),
        "status": "PENDING",
        "status_url": f"/api/v1/jobs/{JOB_ID}",
    }


def test_bulk_submit_maps_active_job_to_409(client, service):
    service.enqueue_error = IndexJobConflictError(ACTIVE_JOB)
    response = client.post("/api/v1/documents/bulk", json={
        "documents": [VALID_PAYLOAD]
    })
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "A search index job is already active.",
        "active_job_id": str(ACTIVE_JOB.id),
        "status_url": f"/api/v1/jobs/{ACTIVE_JOB.id}",
    }


def test_bulk_item_report_is_paginated(client):
    response = client.get(
        f"/api/v1/documents/bulk/{JOB_ID}/items",
        params={"limit": 20, "offset": 0},
    )
    assert response.status_code == 200
    assert response.json()["total_results"] == 2
    assert [item["position"] for item in response.json()["items"]] == [0, 1]
```

Also test empty/oversized envelope `422`, storage/enqueue `503`, unknown and
non-bulk job `404`, malformed UUID `422`, and pagination bounds.

- [ ] **Step 2: Run API tests and observe 404 failures**

```bash
python3 -m pytest tests/integration/test_bulk_ingestion_api.py -q
```

Expected: requests return `404` because routes and dependency are absent.

- [ ] **Step 3: Add dependency and literal routes**

In `app/api/dependencies.py`, construct `BulkIngestionService` with the request
session and a named Celery signature. A named signature is valid before the worker
module is imported by an API process and still sends only the job UUID:

```python
def get_bulk_ingestion_service(
    session: Session = Depends(get_db_session),
) -> BulkIngestionService:
    task = celery_app.signature("documents.bulk_ingest")
    return BulkIngestionService(session, task)
```

Declare both bulk routes in `app/api/v1/documents.py` before
`GET /{document_id}`. The submit route is:

```python
@router.post(
    "/bulk",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def bulk_create_documents(
    payload: BulkDocumentsRequest,
    service: BulkIngestionService = Depends(get_bulk_ingestion_service),
) -> JobAcceptedResponse:
    try:
        job = service.enqueue_documents(payload.documents)
    except IndexJobConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(error),
                "active_job_id": str(error.active_job.id),
                "status_url": f"/api/v1/jobs/{error.active_job.id}",
            },
        ) from error
    except (JobEnqueueError, JobStorageError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JobAcceptedResponse(
        job_id=job.id,
        status=job.status,
        status_url=f"/api/v1/jobs/{job.id}",
    )
```

Implement the report route without returning raw payload content:

```python
@router.get(
    "/bulk/{job_id}/items",
    response_model=IngestionItemListResponse,
)
def list_bulk_ingestion_items(
    job_id: UUID,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: BulkIngestionService = Depends(get_bulk_ingestion_service),
) -> IngestionItemListResponse:
    try:
        total, items = service.list_items(
            job_id, limit=limit, offset=offset
        )
    except BulkIngestionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except JobStorageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return IngestionItemListResponse(
        job_id=job_id,
        total_results=total,
        limit=limit,
        offset=offset,
        items=[IngestionItemResponse.model_validate(item) for item in items],
    )
```

- [ ] **Step 4: Run API and regression route tests**

```bash
python3 -m pytest tests/integration/test_bulk_ingestion_api.py tests/integration/test_document_api.py tests/integration/test_job_api.py -q
```

Expected: all selected tests pass and `/documents/{document_id}` still resolves.

- [ ] **Step 5: Commit and push**

```bash
git add app/api/dependencies.py app/api/v1/documents.py tests/integration/test_bulk_ingestion_api.py
git commit -m "feat: expose bulk document ingestion api"
git push origin main
```

### Task 8: Run Bulk Jobs And Publish One Snapshot

**Files:**
- Create: `app/services/bulk_ingestion_runner.py`
- Create: `tests/unit/test_bulk_ingestion_runner.py`
- Modify: `app/services/job_tracker.py`
- Modify: `app/repositories/ingestion_items.py`
- Modify: `tests/unit/test_job_tracker.py`
- Modify: `tests/unit/test_ingestion_item_repository.py`

**Interfaces:**
- Produces: `BulkIngestionRunner.run(job_id: UUID) -> dict[str, Any]` and `JobTracker.get_job()`.
- Consumes: `IngestionItemProcessor`, `IngestionCounts`, `rebuild_search_index_snapshot()`, and Redis snapshot store.

- [ ] **Step 1: Write failing runner tests**

```python
def test_runner_claims_processes_pending_items_rebuilds_once_and_succeeds():
    result = runner.run(JOB_ID)
    assert processor.processed_ids == [10, 11, 12]
    assert rebuild.calls == [{"index_version": f"redis-{JOB_ID}"}]
    assert result == {
        "received_count": 3,
        "imported_count": 1,
        "skipped_count": 1,
        "failed_count": 1,
        "index_rebuilt": True,
        "index_version": f"redis-{JOB_ID}",
    }
    assert tracker.calls[-1] == (
        "success", JOB_ID, result, 4, "Bulk ingestion completed"
    )


def test_runner_skips_rebuild_when_nothing_was_imported():
    counts.imported = 0
    snapshot_store.active_version = "redis-existing"
    result = runner.run(JOB_ID)
    assert rebuild.calls == []
    assert result["index_rebuilt"] is False
    assert result["index_version"] == "redis-existing"


def test_started_job_resumes_only_pending_items():
    tracker.job.status = STARTED_STATUS
    items.pending_ids = [12]
    runner.run(JOB_ID)
    assert processor.processed_ids == [12]


def test_successful_redelivery_returns_stored_result_without_work():
    tracker.job.status = SUCCESS_STATUS
    tracker.job.result = SUCCESS_RESULT
    assert runner.run(JOB_ID) == SUCCESS_RESULT
    assert processor.processed_ids == []
    assert rebuild.calls == []
```

Also test wrong job type, missing job, failure terminal state, progress after each
processed item, and rebuild failure propagation without marking success.

- [ ] **Step 2: Run runner tests and confirm failure**

```bash
python3 -m pytest tests/unit/test_bulk_ingestion_runner.py -q
```

Expected: collection fails because the runner module does not exist.

- [ ] **Step 3: Add read/resume support and implement the runner**

Add `JobTracker.get_job(job_id) -> Job | None` using a short session. In
`app/services/bulk_ingestion_runner.py`, define a short-transaction read store so
the runner never holds one ORM session while the per-item processor commits:

```python
T = TypeVar("T")


class IngestionItemStore:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        repository_factory: Callable[
            [Session], IngestionItemRepository
        ] = IngestionItemRepository,
    ) -> None:
        self.session_factory = session_factory
        self.repository_factory = repository_factory

    def list_pending_ids(self, job_id: UUID) -> list[int]:
        return self._read(
            lambda repository: repository.list_pending_ids(job_id)
        )

    def count_terminal(self, job_id: UUID) -> int:
        return self._read(
            lambda repository: repository.count_terminal(job_id)
        )

    def counts(self, job_id: UUID) -> IngestionCounts:
        return self._read(lambda repository: repository.counts(job_id))

    def _read(self, operation: Callable[[IngestionItemRepository], T]) -> T:
        session = self.session_factory()
        try:
            return operation(self.repository_factory(session))
        finally:
            session.close()
```

`BulkIngestionRunner` accepts injected tracker, item store, processor, rebuild
callable, and snapshot store:

```python
class BulkIngestionRunner:
    def __init__(
        self,
        tracker: JobTracker | None = None,
        item_store: IngestionItemStore | None = None,
        processor: IngestionItemProcessor | None = None,
        rebuild: Callable[[str], dict[str, Any]] = rebuild_search_index_snapshot,
        snapshot_store: RedisSearchIndexStore | None = None,
    ) -> None:
        self.tracker = tracker or JobTracker()
        self.item_store = item_store or IngestionItemStore()
        self.processor = processor or IngestionItemProcessor()
        self.rebuild = rebuild
        self.snapshot_store = (
            snapshot_store or create_redis_search_index_store()
        )
```

Its `run()` method must be:

```python
def run(self, job_id: UUID) -> dict[str, Any]:
    job = self.tracker.get_job(job_id)
    if job is None or job.job_type != BULK_DOCUMENT_INGESTION_JOB:
        raise JobTransitionError("Bulk ingestion job is missing or invalid.")
    if job.status == SUCCESS_STATUS:
        return dict(job.result or {})
    if job.status == FAILURE_STATUS:
        raise JobTransitionError("Bulk ingestion job has already failed.")
    if job.progress_total is None or job.progress_total < 2:
        raise JobTransitionError("Bulk ingestion job has invalid progress metadata.")
    if job.status == PENDING_STATUS:
        claimed = self.tracker.claim(
            job_id,
            progress_current=0,
            progress_total=job.progress_total,
            progress_message="Processing documents",
        )
        if not claimed:
            raise JobTransitionError("Bulk ingestion job could not be claimed.")

    pending_ids = self.item_store.list_pending_ids(job_id)
    completed = self.item_store.count_terminal(job_id)
    for item_id in pending_ids:
        self.processor.process(item_id)
        completed += 1
        self.tracker.update_progress(
            job_id,
            progress_current=completed,
            progress_total=job.progress_total,
            progress_message=f"Processed document {completed} of {job.progress_total - 1}",
        )

    counts = self.item_store.counts(job_id)
    result = self._publish_or_reuse_index(job_id, counts)
    self.tracker.mark_success(
        job_id,
        result=result,
        progress_total=counts.received + 1,
        progress_message="Bulk ingestion completed",
    )
    return result
```

Implement `_publish_or_reuse_index()` with this exact result contract:

```python
def _publish_or_reuse_index(
    self,
    job_id: UUID,
    counts: IngestionCounts,
) -> dict[str, Any]:
    if counts.imported:
        self.tracker.update_progress(
            job_id,
            progress_current=counts.received,
            progress_total=counts.received + 1,
            progress_message="Rebuilding search index",
        )
        status = self.rebuild(f"redis-{job_id}")
        index_version = status["index_version"]
        index_rebuilt = True
    else:
        self.tracker.update_progress(
            job_id,
            progress_current=counts.received,
            progress_total=counts.received + 1,
            progress_message="No index changes required",
        )
        index_version = self.snapshot_store.get_active_version()
        index_rebuilt = False

    return {
        "received_count": counts.received,
        "imported_count": counts.imported,
        "skipped_count": counts.skipped,
        "failed_count": counts.failed,
        "index_rebuilt": index_rebuilt,
        "index_version": index_version,
    }
```

- [ ] **Step 4: Run runner, tracker, repository, and snapshot tests**

```bash
python3 -m pytest tests/unit/test_bulk_ingestion_runner.py tests/unit/test_job_tracker.py tests/unit/test_ingestion_item_repository.py tests/unit/test_worker_search_tasks.py tests/unit/test_search_snapshots.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit and push**

```bash
git add app/services/bulk_ingestion_runner.py app/services/job_tracker.py app/repositories/ingestion_items.py tests/unit/test_bulk_ingestion_runner.py tests/unit/test_job_tracker.py tests/unit/test_ingestion_item_repository.py
git commit -m "feat: run bulk ingestion job lifecycle"
git push origin main
```

### Task 9: Add Celery Retry And Duplicate-Delivery Safety

**Files:**
- Create: `app/services/advisory_locks.py`
- Create: `app/workers/ingestion_tasks.py`
- Create: `tests/unit/test_worker_ingestion_tasks.py`
- Modify: `app/workers/celery_app.py`

**Interfaces:**
- Produces: `PostgresAdvisoryLock.acquire(job_id)`, `execute_bulk_ingestion_attempt()`, and Celery task `documents.bulk_ingest`.
- Consumes: `BulkIngestionRunner` and `JobTracker`.

- [ ] **Step 1: Write failing task and lock tests**

```python
def test_advisory_lock_uses_job_uuid_and_always_unlocks():
    with lock.acquire(JOB_UUID):
        assert connection.executed[0].startswith("select pg_try_advisory_lock")
    assert connection.executed[-1].startswith("select pg_advisory_unlock")
    assert connection.closed is True


def test_busy_lock_does_not_execute_duplicate_delivery():
    lock.acquired = False
    with pytest.raises(Ignore):
        execute_bulk_ingestion_attempt(context, JOB_ID, runner, lock, tracker)
    assert runner.calls == []
    assert tracker.failed_error is None


def test_transient_error_retries_with_increasing_delay_and_safe_progress():
    context.request.retries = 1
    runner.error = OperationalError("statement", {}, ConnectionError("secret"))
    with pytest.raises(FakeRetry):
        execute_bulk_ingestion_attempt(context, JOB_ID, runner, lock, tracker)
    assert context.retry_with["countdown"] == 4
    assert tracker.progress_message == "Temporary failure; retrying"


def test_exhausted_retry_marks_failure_and_reraises():
    context.request.retries = 3
    runner.error = RedisConnectionError("redis password leaked")
    with pytest.raises(RedisConnectionError):
        execute_bulk_ingestion_attempt(context, JOB_ID, runner, lock, tracker)
    assert tracker.failed_error == "Bulk ingestion failed."


def test_task_configuration_supports_worker_crash_redelivery():
    assert bulk_ingest_documents_task.name == "documents.bulk_ingest"
    assert bulk_ingest_documents_task.acks_late is True
    assert bulk_ingest_documents_task.reject_on_worker_lost is True
    assert bulk_ingest_documents_task.max_retries == 3
```

Also test permanent errors do not retry, failure-recording errors do not replace
the original exception, task/public id mismatch, and successful task delegation.

- [ ] **Step 2: Run tests and confirm missing modules**

```bash
python3 -m pytest tests/unit/test_worker_ingestion_tasks.py -q
```

Expected: collection fails because the lock and task modules are absent.

- [ ] **Step 3: Implement PostgreSQL advisory locking**

Use one dedicated SQLAlchemy connection for the lock lifetime:

```python
class JobAlreadyRunningError(Exception):
    pass


class PostgresAdvisoryLock:
    def __init__(self, connection_factory=engine.connect) -> None:
        self.connection_factory = connection_factory

    @contextmanager
    def acquire(self, job_id: UUID):
        connection = self.connection_factory()
        try:
            lock_key = str(job_id)
            acquired = connection.scalar(text(
                "select pg_try_advisory_lock(hashtextextended(:key, 0))"
            ), {"key": lock_key})
            if not acquired:
                raise JobAlreadyRunningError(f"Job {job_id} is already running.")
            try:
                yield
            finally:
                connection.execute(text(
                    "select pg_advisory_unlock(hashtextextended(:key, 0))"
                ), {"key": lock_key})
        finally:
            connection.close()
```

The public task error must never expose the job id lock exception through the API;
it remains a worker concern.

- [ ] **Step 4: Implement bounded retry task**

Create a bound task with:

```python
@celery_app.task(
    bind=True,
    name="documents.bulk_ingest",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def bulk_ingest_documents_task(task: Task, job_id: str) -> dict[str, Any]:
    if task.request.id is None or task.request.id != job_id:
        raise RuntimeError("Celery task id does not match durable job id.")
    return execute_bulk_ingestion_attempt(
        task,
        UUID(job_id),
        runner_factory=BulkIngestionRunner,
        lock_factory=PostgresAdvisoryLock,
        tracker_factory=JobTracker,
    )
```

Implement the attempt helper so Celery's `Retry` exception cannot fall through to
permanent-failure handling:

```python
TRANSIENT_ERRORS = (
    OperationalError,
    RedisConnectionError,
    RedisTimeoutError,
)


def execute_bulk_ingestion_attempt(
    task: Task,
    job_id: UUID,
    *,
    runner_factory: Callable[[], BulkIngestionRunner],
    lock_factory: Callable[[], PostgresAdvisoryLock],
    tracker_factory: Callable[[], JobTracker],
) -> dict[str, Any]:
    tracker = tracker_factory()
    try:
        with lock_factory().acquire(job_id):
            return runner_factory().run(job_id)
    except JobAlreadyRunningError as error:
        raise Ignore() from error
    except TRANSIENT_ERRORS as error:
        if task.request.retries < task.max_retries:
            _record_retry_progress(tracker, job_id)
            raise task.retry(
                exc=error,
                countdown=2 ** (task.request.retries + 1),
            )
        logger.exception("Bulk ingestion job %s exhausted retries.", job_id)
        _record_final_failure(tracker, job_id)
        raise
    except Exception:
        logger.exception("Bulk ingestion job %s failed.", job_id)
        _record_final_failure(tracker, job_id)
        raise


def _record_retry_progress(tracker: JobTracker, job_id: UUID) -> None:
    try:
        job = tracker.get_job(job_id)
        if job is not None and job.status == STARTED_STATUS:
            tracker.update_progress(
                job_id,
                progress_current=job.progress_current,
                progress_total=job.progress_total,
                progress_message="Temporary failure; retrying",
            )
    except Exception:
        logger.exception("Could not record retry progress for job %s.", job_id)


def _record_final_failure(tracker: JobTracker, job_id: UUID) -> None:
    try:
        tracker.mark_failure(job_id, error="Bulk ingestion failed.")
    except Exception:
        logger.exception("Could not record failure for job %s.", job_id)
```

The original delivery owns the durable job when the advisory lock is busy, so a
duplicate must neither retry nor mark failure. Add `app.workers.ingestion_tasks`
to Celery's configured imports.

- [ ] **Step 5: Run task, Celery configuration, and service tests**

```bash
python3 -m pytest tests/unit/test_worker_ingestion_tasks.py tests/unit/test_celery_config.py tests/unit/test_bulk_ingestion.py -q
```

Expected: all selected tests pass and Celery registers both rebuild and bulk task modules.

- [ ] **Step 6: Commit and push**

```bash
git add app/services/advisory_locks.py app/workers/ingestion_tasks.py app/workers/celery_app.py tests/unit/test_worker_ingestion_tasks.py tests/unit/test_celery_config.py
git commit -m "feat: make bulk ingestion jobs retryable"
git push origin main
```

### Task 10: Verify The Complete Live Flow And Document It

**Files:**
- Create: `tests/integration/test_bulk_ingestion_e2e.py`
- Create: `docs/bulk-ingestion.md`
- Modify: `tests/integration/test_bulk_ingestion_postgres.py`
- Modify: `docs/job-tracking.md`
- Modify: `docs/celery-worker.md`

**Interfaces:**
- Produces: verified end-to-end behavior and operator documentation.
- Consumes: all prior tasks.

- [ ] **Step 1: Write the live end-to-end test**

Under the PostgreSQL marker, use unique URLs and real PostgreSQL/Redis stores. The
test must stage this mixed batch through `BulkIngestionService`, execute the task
synchronously with the durable task id, and inspect persisted state:

```python
payloads = [
    {
        "title": "Bulk BM25 Snapshot",
        "content": "uniquebulkingestiontoken20260721",
        "url": unique_url,
    },
    {
        "title": "Duplicate Bulk BM25 Snapshot",
        "content": "duplicate content",
        "url": unique_url,
    },
    {"title": "Missing content"},
]

assert completed.status == SUCCESS_STATUS
assert completed.result == {
    "received_count": 3,
    "imported_count": 1,
    "skipped_count": 1,
    "failed_count": 1,
    "index_rebuilt": True,
    "index_version": f"redis-{job.id}",
}
assert [item.status for item in report_items] == [
    IMPORTED_ITEM_STATUS,
    SKIPPED_ITEM_STATUS,
    FAILED_ITEM_STATUS,
]
assert search_response.total_results == 1
assert search_response.results[0].title == "Bulk BM25 Snapshot"
```

Capture the previous Redis active-version value before execution. In teardown,
delete only the snapshot created by this job, restore the previous pointer (or
delete it when previously absent), and delete only PostgreSQL rows created by
this test. Do not delete the user's existing live documents or historical jobs.

- [ ] **Step 2: Run the live end-to-end test**

```bash
docker compose up -d postgres redis
alembic upgrade head
RUN_POSTGRES_INTEGRATION=1 python3 -m pytest tests/integration/test_bulk_ingestion_e2e.py -q
```

Expected: the test passes with this complete flow:

```text
API stages job/items -> Celery receives job id -> worker imports 1/skips 1/fails 1
-> Redis active version becomes redis-<job-id> -> durable job succeeds
-> item report is ordered -> BM25 search finds the imported document
```

- [ ] **Step 3: Write operator documentation**

`docs/bulk-ingestion.md` must include these runnable commands:

```bash
docker compose up -d postgres redis
alembic upgrade head
celery -A app.workers.celery_app.celery_app worker --loglevel=info
uvicorn app.main:app --reload
curl -X POST http://127.0.0.1:8000/api/v1/documents/bulk \
  -H 'Content-Type: application/json' \
  -d '{"documents":[{"title":"BM25","content":"BM25 ranking","url":"https://example.com/bm25-bulk"}]}'
curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID
curl 'http://127.0.0.1:8000/api/v1/documents/bulk/JOB_ID/items?limit=100&offset=0'
```

Document partial success, duplicate URL rules, progress total `N + 1`, `409`
conflicts, three transient retries, safe errors, and indefinite v1 retention.
Update existing job and worker docs so they no longer claim concurrency is scoped
only to rebuild jobs.

- [ ] **Step 4: Run focused, full, and live verification**

```bash
python3 -m pytest -q
RUN_POSTGRES_INTEGRATION=1 python3 -m pytest tests/integration/test_bulk_ingestion_postgres.py tests/integration/test_bulk_ingestion_e2e.py tests/integration/test_job_repository_postgres.py tests/integration/test_job_api_postgres.py -q
git diff --check
```

Expected: the default suite passes with PostgreSQL-marked tests skipped, all
selected live PostgreSQL/Redis tests pass, and `git diff --check` prints nothing.

- [ ] **Step 5: Perform a real worker/API smoke test**

Start Celery and Uvicorn in separate sessions, submit the documented mixed batch,
poll `/api/v1/jobs/{job_id}` to `SUCCESS`, inspect ordered item outcomes, and
search for the unique token. Confirm Redis reports the job-derived active version:

```bash
docker compose exec -T redis redis-cli GET search:index:active_version
```

Expected: `redis-<job-id>` and one BM25 result for the imported document.

- [ ] **Step 6: Commit and push**

```bash
git add app tests docs alembic
git commit -m "test: verify durable bulk ingestion flow"
git push origin main
```

- [ ] **Step 7: Final repository verification**

```bash
git status --short --branch
git log -10 --oneline --decorate
```

Expected: clean `main`, synchronized with `origin/main`, with one focused commit
for each completed task in this plan.
