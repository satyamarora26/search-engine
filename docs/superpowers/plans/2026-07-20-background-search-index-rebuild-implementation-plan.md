# Background Search Index Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the synchronous search-index rebuild with a Celery job that publishes a versioned Redis snapshot, expose job status through FastAPI, and make API processes activate the newest valid snapshot before searching.

**Architecture:** PostgreSQL remains the document source of truth. A Celery worker validates and publishes JSON document snapshots through a focused Redis store; each FastAPI process compares snapshot versions and atomically rebuilds its process-local `SearchIndexService` only when the active version changes. FastAPI exposes the existing rebuild path as an asynchronous `202 Accepted` operation and a generic job-status endpoint backed by Celery `AsyncResult`.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, Celery, Redis, PostgreSQL, SQLAlchemy, pytest.

## Global Constraints

- Redis snapshots contain explicit JSON data; do not use pickle.
- Snapshot keys are `search:index:snapshot:{version}` and `search:index:active_version`.
- Snapshot `format_version` is the integer `1`.
- Snapshot index versions use `redis-{celery_task_id}`.
- Publish the complete immutable snapshot before updating the active-version pointer.
- The API must preserve and serve the last valid local index when Redis is unavailable or snapshot validation fails.
- `POST /api/v1/search/rebuild` must return HTTP `202 Accepted` without loading PostgreSQL inline.
- Failed job responses expose `Background job failed.` and never raw exception text.
- Unit and API tests must not require a live Redis server or Celery worker.
- Use TDD for every production behavior: write one failing test, observe the expected failure, then add the minimum implementation.
- Commit and push each completed task to `origin/codex/task-1-scaffold`.

---

### Task 1: Versioned Redis Snapshot Store

**Files:**
- Modify: `requirements.txt`
- Create: `app/schemas/search_snapshots.py`
- Create: `app/services/search_snapshots.py`
- Create: `tests/unit/test_search_snapshots.py`

**Interfaces:**
- Produces: `SearchSnapshotDocument` with fields `id`, `title`, `content`, and nullable `url`.
- Produces: `SearchIndexSnapshot` with fields `format_version`, `index_version`, and `documents`.
- Produces: `RedisSearchIndexStore.publish(snapshot: SearchIndexSnapshot) -> None`.
- Produces: `RedisSearchIndexStore.get_active_version() -> str | None`.
- Produces: `RedisSearchIndexStore.load_snapshot(version: str) -> SearchIndexSnapshot | None`.
- Produces: `create_redis_search_index_store(settings: Settings | None = None) -> RedisSearchIndexStore`.

- [ ] **Step 1: Write snapshot schema round-trip tests**

Create `tests/unit/test_search_snapshots.py` with a small in-memory Redis fake and tests that define the payload contract:

```python
import pytest
from pydantic import ValidationError

from app.schemas.search_snapshots import (
    SearchIndexSnapshot,
    SearchSnapshotDocument,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []
        self.fail_on_key: str | None = None

    def set(self, name: str, value: str) -> bool:
        self.set_calls.append((name, value))
        if name == self.fail_on_key:
            raise ConnectionError("redis write failed")
        self.values[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)


def build_snapshot() -> SearchIndexSnapshot:
    return SearchIndexSnapshot(
        index_version="redis-task-123",
        documents=[
            SearchSnapshotDocument(
                id=1,
                title="BM25",
                content="BM25 uses term saturation.",
                url=None,
            )
        ],
    )


def test_snapshot_json_round_trip_preserves_nullable_url():
    snapshot = build_snapshot()

    restored = SearchIndexSnapshot.model_validate_json(snapshot.model_dump_json())

    assert restored == snapshot
    assert restored.format_version == 1
    assert restored.documents[0].url is None


def test_snapshot_rejects_unknown_format_version():
    with pytest.raises(ValidationError):
        SearchIndexSnapshot.model_validate(
            {"format_version": 2, "index_version": "redis-v2", "documents": []}
        )
```

- [ ] **Step 2: Run the schema tests and observe RED**

Run:

```bash
pytest tests/unit/test_search_snapshots.py -v
```

Expected: collection fails because `app.schemas.search_snapshots` does not exist.

- [ ] **Step 3: Implement the explicit Pydantic snapshot schema**

Add `redis` as a direct dependency in `requirements.txt`, then create `app/schemas/search_snapshots.py`:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SearchSnapshotDocument(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    url: str | None = None


class SearchIndexSnapshot(BaseModel):
    format_version: Literal[1] = 1
    index_version: str
    documents: list[SearchSnapshotDocument]
```

- [ ] **Step 4: Run the schema tests and observe GREEN**

Run:

```bash
pytest tests/unit/test_search_snapshots.py -v
```

Expected: the two schema tests pass.

- [ ] **Step 5: Add failing publication and loading tests**

Add this import beside the schema imports in `tests/unit/test_search_snapshots.py`:

```python
from app.services.search_snapshots import RedisSearchIndexStore
```

Then append these tests:

```python
def test_publish_writes_snapshot_before_active_pointer():
    redis = FakeRedis()
    store = RedisSearchIndexStore(redis)
    snapshot = build_snapshot()

    store.publish(snapshot)

    assert [call[0] for call in redis.set_calls] == [
        "search:index:snapshot:redis-task-123",
        "search:index:active_version",
    ]
    assert store.get_active_version() == "redis-task-123"
    assert store.load_snapshot("redis-task-123") == snapshot


def test_snapshot_write_failure_preserves_previous_active_version():
    redis = FakeRedis()
    redis.values["search:index:active_version"] = "redis-old"
    redis.fail_on_key = "search:index:snapshot:redis-task-123"
    store = RedisSearchIndexStore(redis)

    with pytest.raises(ConnectionError, match="redis write failed"):
        store.publish(build_snapshot())

    assert store.get_active_version() == "redis-old"


def test_load_snapshot_returns_none_for_missing_version():
    store = RedisSearchIndexStore(FakeRedis())

    assert store.load_snapshot("redis-missing") is None
```

- [ ] **Step 6: Run the store tests and observe RED**

Run:

```bash
pytest tests/unit/test_search_snapshots.py -v
```

Expected: the store tests fail because `RedisSearchIndexStore` has not been implemented.

- [ ] **Step 7: Implement the Redis snapshot store**

Create `app/services/search_snapshots.py`:

```python
from typing import Protocol

from redis import Redis

from app.core.config import Settings, get_settings
from app.schemas.search_snapshots import SearchIndexSnapshot

ACTIVE_INDEX_VERSION_KEY = "search:index:active_version"
INDEX_SNAPSHOT_KEY_PREFIX = "search:index:snapshot:"


class RedisClient(Protocol):
    def set(self, name: str, value: str) -> object: ...

    def get(self, name: str) -> str | bytes | None: ...


class RedisSearchIndexStore:
    def __init__(self, client: RedisClient) -> None:
        self.client = client

    def publish(self, snapshot: SearchIndexSnapshot) -> None:
        snapshot_key = self._snapshot_key(snapshot.index_version)
        self.client.set(snapshot_key, snapshot.model_dump_json())
        self.client.set(ACTIVE_INDEX_VERSION_KEY, snapshot.index_version)

    def get_active_version(self) -> str | None:
        return _decode(self.client.get(ACTIVE_INDEX_VERSION_KEY))

    def load_snapshot(self, version: str) -> SearchIndexSnapshot | None:
        payload = self.client.get(self._snapshot_key(version))
        if payload is None:
            return None
        return SearchIndexSnapshot.model_validate_json(payload)

    @staticmethod
    def _snapshot_key(version: str) -> str:
        return f"{INDEX_SNAPSHOT_KEY_PREFIX}{version}"


def create_redis_search_index_store(
    settings: Settings | None = None,
) -> RedisSearchIndexStore:
    worker_settings = settings or get_settings()
    client = Redis.from_url(worker_settings.redis_url, decode_responses=True)
    return RedisSearchIndexStore(client)


def _decode(value: str | bytes | None) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value
```

- [ ] **Step 8: Verify Task 1 and commit**

Run:

```bash
pytest tests/unit/test_search_snapshots.py tests/unit/test_config.py -v
git diff --check
```

Expected: all focused tests pass and `git diff --check` exits `0`.

Commit and push:

```bash
git add requirements.txt app/schemas/search_snapshots.py app/services/search_snapshots.py tests/unit/test_search_snapshots.py
git commit -m "feat: add versioned redis search snapshots"
git push origin codex/task-1-scaffold
```

---

### Task 2: Fail-Open Local Index Synchronization

**Files:**
- Modify: `app/services/search_index.py`
- Create: `app/services/search_index_sync.py`
- Modify: `tests/unit/search/test_search_index_service.py`
- Create: `tests/unit/search/test_search_index_sync.py`

**Interfaces:**
- Consumes: `RedisSearchIndexStore.get_active_version()` and `load_snapshot(version)` from Task 1.
- Produces: `SearchIndexService.rebuild(documents, *, index_version: str | None = None) -> SearchIndexStatus`.
- Produces: `SearchIndexSynchronizer.synchronize() -> SearchIndexService`.
- Produces: `get_synchronized_search_index_service() -> SearchIndexService` for FastAPI dependency injection.

- [ ] **Step 1: Write the failing version activation test**

Append to `tests/unit/search/test_search_index_service.py`:

```python
def test_rebuild_can_atomically_activate_a_new_index_version():
    service = SearchIndexService(index_version="redis-old")

    status = service.rebuild(
        [IndexedDocument(id=8, title="Redis", content="shared snapshot")],
        index_version="redis-new",
    )

    assert status.index_version == "redis-new"
    assert service.search("shared snapshot").index_version == "redis-new"
```

- [ ] **Step 2: Run the test and observe RED**

Run:

```bash
pytest tests/unit/search/test_search_index_service.py::test_rebuild_can_atomically_activate_a_new_index_version -v
```

Expected: fail because `rebuild` does not accept `index_version`.

- [ ] **Step 3: Add version-aware atomic rebuild**

Change `SearchIndexService.rebuild` to accept a keyword-only optional version. Build the replacement engine outside the lock, then swap all mutable state inside one lock:

```python
def rebuild(
    self,
    documents: Iterable[Any],
    *,
    index_version: str | None = None,
) -> SearchIndexStatus:
    indexed_documents = [_to_indexed_document(document) for document in documents]
    engine = SearchEngine()
    for document in indexed_documents:
        engine.index_document(document)

    with self._lock:
        self._engine = engine
        self._documents_by_id = {
            document.id: document for document in indexed_documents
        }
        if index_version is not None:
            self.index_version = index_version
        return self.status()
```

- [ ] **Step 4: Run the version activation test and observe GREEN**

Run:

```bash
pytest tests/unit/search/test_search_index_service.py -v
```

Expected: every `SearchIndexService` unit test passes.

- [ ] **Step 5: Write synchronizer tests for changed, unchanged, and failed snapshots**

Create `tests/unit/search/test_search_index_sync.py`:

```python
from app.schemas.search_snapshots import (
    SearchIndexSnapshot,
    SearchSnapshotDocument,
)
from app.search.types import IndexedDocument
from app.services.search_index import SearchIndexService
from app.services.search_index_sync import SearchIndexSynchronizer


class FakeSnapshotStore:
    def __init__(
        self,
        active_version: str | None,
        snapshot: SearchIndexSnapshot | None = None,
        error: Exception | None = None,
    ) -> None:
        self.active_version = active_version
        self.snapshot = snapshot
        self.error = error
        self.loaded_versions: list[str] = []

    def get_active_version(self) -> str | None:
        if self.error:
            raise self.error
        return self.active_version

    def load_snapshot(self, version: str) -> SearchIndexSnapshot | None:
        self.loaded_versions.append(version)
        if self.error:
            raise self.error
        return self.snapshot


def test_synchronize_activates_new_valid_snapshot():
    service = SearchIndexService(
        [IndexedDocument(id=1, title="Old", content="old content")],
        index_version="redis-old",
    )
    snapshot = SearchIndexSnapshot(
        index_version="redis-new",
        documents=[
            SearchSnapshotDocument(
                id=2,
                title="New",
                content="new searchable content",
                url=None,
            )
        ],
    )
    synchronizer = SearchIndexSynchronizer(
        service,
        FakeSnapshotStore("redis-new", snapshot),
    )

    synchronized = synchronizer.synchronize()

    assert synchronized is service
    assert service.search("old content").total_results == 0
    assert service.search("new searchable").index_version == "redis-new"


def test_synchronize_does_not_load_matching_version():
    service = SearchIndexService(index_version="redis-current")
    store = FakeSnapshotStore("redis-current")

    SearchIndexSynchronizer(service, store).synchronize()

    assert store.loaded_versions == []


def test_synchronize_preserves_local_index_when_redis_fails(caplog):
    service = SearchIndexService(
        [IndexedDocument(id=1, title="Stable", content="stable content")],
        index_version="redis-stable",
    )
    store = FakeSnapshotStore(None, error=ConnectionError("redis unavailable"))

    synchronized = SearchIndexSynchronizer(service, store).synchronize()

    assert synchronized.search("stable").total_results == 1
    assert synchronized.status().index_version == "redis-stable"
    assert "Could not synchronize search index" in caplog.text


def test_synchronize_preserves_local_index_when_snapshot_is_missing(caplog):
    service = SearchIndexService(
        [IndexedDocument(id=1, title="Stable", content="stable content")],
        index_version="redis-stable",
    )
    store = FakeSnapshotStore("redis-new", snapshot=None)

    SearchIndexSynchronizer(service, store).synchronize()

    assert service.search("stable").total_results == 1
    assert service.status().index_version == "redis-stable"
    assert "Could not synchronize search index" in caplog.text
```

- [ ] **Step 6: Run synchronizer tests and observe RED**

Run:

```bash
pytest tests/unit/search/test_search_index_sync.py -v
```

Expected: collection fails because `app.services.search_index_sync` does not exist.

- [ ] **Step 7: Implement fail-open synchronization and the production dependency**

Create `app/services/search_index_sync.py`:

```python
import logging

from app.services.search_index import SearchIndexService, get_search_index_service
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)

logger = logging.getLogger(__name__)


class SearchIndexSynchronizer:
    def __init__(
        self,
        search_index: SearchIndexService,
        snapshot_store: RedisSearchIndexStore,
    ) -> None:
        self.search_index = search_index
        self.snapshot_store = snapshot_store

    def synchronize(self) -> SearchIndexService:
        try:
            active_version = self.snapshot_store.get_active_version()
            if active_version is None:
                return self.search_index
            if active_version == self.search_index.status().index_version:
                return self.search_index

            snapshot = self.snapshot_store.load_snapshot(active_version)
            if snapshot is None:
                raise ValueError(f"Active search snapshot {active_version} is missing.")
            if snapshot.index_version != active_version:
                raise ValueError("Active search snapshot version does not match its key.")

            self.search_index.rebuild(
                snapshot.documents,
                index_version=active_version,
            )
        except Exception:
            logger.warning("Could not synchronize search index; using local index.", exc_info=True)
        return self.search_index


_search_index_synchronizer = SearchIndexSynchronizer(
    get_search_index_service(),
    create_redis_search_index_store(),
)


def get_synchronized_search_index_service() -> SearchIndexService:
    return _search_index_synchronizer.synchronize()
```

- [ ] **Step 8: Verify Task 2 and commit**

Run:

```bash
pytest tests/unit/search/test_search_index_service.py tests/unit/search/test_search_index_sync.py -v
git diff --check
```

Expected: focused search-index tests pass and formatting checks are clean.

Commit and push:

```bash
git add app/services/search_index.py app/services/search_index_sync.py tests/unit/search/test_search_index_service.py tests/unit/search/test_search_index_sync.py
git commit -m "feat: synchronize search index from redis snapshots"
git push origin codex/task-1-scaffold
```

---

### Task 3: Celery Snapshot Publication

**Files:**
- Modify: `app/workers/celery_app.py`
- Modify: `app/workers/search_tasks.py`
- Modify: `tests/unit/test_celery_config.py`
- Modify: `tests/unit/test_worker_search_tasks.py`

**Interfaces:**
- Consumes: `SearchIndexSnapshot`, `SearchSnapshotDocument`, and `create_redis_search_index_store()` from Task 1.
- Produces: `rebuild_search_index_snapshot(index_version: str, session_factory=SessionLocal, store_factory=create_redis_search_index_store) -> dict[str, Any]`.
- Produces: bound Celery task `search.rebuild_index_snapshot` using `redis-{task_id}`.

- [ ] **Step 1: Write failing worker publication tests**

Update `tests/unit/test_worker_search_tasks.py` so the successful helper test supplies an index version and fake store:

```python
import pytest


class FakeSnapshotStore:
    def __init__(self) -> None:
        self.published = []

    def publish(self, snapshot) -> None:
        self.published.append(snapshot)


def test_rebuild_search_index_snapshot_publishes_documents_and_version():
    session = FakeSession(
        [
            Document(
                id=1,
                title="Worker BM25 Document",
                content="background indexing with celery",
                url="https://example.com/worker-bm25",
            ),
            Document(
                id=2,
                title="Worker TFIDF Document",
                content="background indexing with redis",
                url=None,
            ),
        ]
    )
    store = FakeSnapshotStore()

    status = rebuild_search_index_snapshot(
        "redis-task-123",
        session_factory=lambda: session,
        store_factory=lambda: store,
    )

    assert status == {"index_version": "redis-task-123", "document_count": 2}
    assert store.published[0].index_version == "redis-task-123"
    assert [document.id for document in store.published[0].documents] == [1, 2]
    assert store.published[0].documents[1].url is None
    assert session.closed is True
```

Remove the old `WORKER_SEARCH_INDEX_SNAPSHOT_VERSION` import because task ids now
produce versions. Keep the existing session-failure test, but pass
`"redis-task-failure"` and a fake `store_factory`. Add a publication-failure test:

```python
def test_rebuild_search_index_snapshot_closes_session_when_publish_fails():
    class BrokenStore:
        def publish(self, snapshot) -> None:
            raise ConnectionError("redis failed")

    session = FakeSession([])

    with pytest.raises(ConnectionError, match="redis failed"):
        rebuild_search_index_snapshot(
            "redis-task-failure",
            session_factory=lambda: session,
            store_factory=BrokenStore,
        )

    assert session.closed is True
```

Add a task-boundary test that executes eagerly without a broker and proves the
Celery task id becomes the snapshot version:

```python
def test_rebuild_task_derives_version_from_celery_task_id(monkeypatch):
    called_with: list[str] = []

    def fake_rebuild(index_version: str):
        called_with.append(index_version)
        return {"index_version": index_version, "document_count": 0}

    monkeypatch.setattr(
        "app.workers.search_tasks.rebuild_search_index_snapshot",
        fake_rebuild,
    )

    result = rebuild_search_index_snapshot_task.apply(task_id="task-123")

    assert result.successful() is True
    assert result.result == {
        "index_version": "redis-task-123",
        "document_count": 0,
    }
    assert called_with == ["redis-task-123"]
```

- [ ] **Step 2: Run worker tests and observe RED**

Run:

```bash
pytest tests/unit/test_worker_search_tasks.py -v
```

Expected: fail because the helper does not accept `index_version` or `store_factory` and does not publish.

- [ ] **Step 3: Implement snapshot publication and bind the Celery task**

Change `app/workers/search_tasks.py` to this shape:

```python
from collections.abc import Callable
from typing import Any

from celery import Task
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.repositories.documents import DocumentRepository
from app.schemas.search_snapshots import (
    SearchIndexSnapshot,
    SearchSnapshotDocument,
)
from app.services.search_index import SearchIndexService
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)
from app.workers.celery_app import celery_app


def rebuild_search_index_snapshot(
    index_version: str,
    session_factory: Callable[[], Session] = SessionLocal,
    store_factory: Callable[[], RedisSearchIndexStore] = create_redis_search_index_store,
) -> dict[str, Any]:
    session = session_factory()
    try:
        documents = DocumentRepository(session).list_all_active()
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
        store_factory().publish(snapshot)
        return status.model_dump()
    finally:
        session.close()


@celery_app.task(bind=True, name="search.rebuild_index_snapshot")
def rebuild_search_index_snapshot_task(task: Task) -> dict[str, Any]:
    if task.request.id is None:
        raise RuntimeError("Celery rebuild task id is required.")
    return rebuild_search_index_snapshot(f"redis-{task.request.id}")
```

- [ ] **Step 4: Run worker tests and observe GREEN**

Run:

```bash
pytest tests/unit/test_worker_search_tasks.py -v
```

Expected: worker helper publication, failure cleanup, and stable task-name tests pass.

- [ ] **Step 5: Write and implement the `STARTED` state configuration test**

Add to `tests/unit/test_celery_config.py`:

```python
def test_create_celery_app_tracks_started_tasks():
    celery_app = create_celery_app()

    assert celery_app.conf.task_track_started is True
```

Run it first and observe failure:

```bash
pytest tests/unit/test_celery_config.py::test_create_celery_app_tracks_started_tasks -v
```

Then add `task_track_started=True` to the existing `celery_app.conf.update(...)` call and rerun the complete Celery configuration test file.

- [ ] **Step 6: Verify Task 3 and commit**

Run:

```bash
pytest tests/unit/test_worker_search_tasks.py tests/unit/test_celery_config.py -v
git diff --check
```

Expected: worker and Celery configuration tests pass.

Commit and push:

```bash
git add app/workers/celery_app.py app/workers/search_tasks.py tests/unit/test_celery_config.py tests/unit/test_worker_search_tasks.py
git commit -m "feat: publish search snapshots from celery"
git push origin codex/task-1-scaffold
```

---

### Task 4: Asynchronous Rebuild And Job Status API

**Files:**
- Create: `app/schemas/jobs.py`
- Create: `app/services/jobs.py`
- Create: `app/api/v1/jobs.py`
- Modify: `app/api/v1/router.py`
- Modify: `app/api/v1/search.py`
- Create: `tests/unit/test_jobs.py`
- Create: `tests/integration/test_job_api.py`

**Interfaces:**
- Produces: `JobAcceptedResponse`.
- Produces: `JobStatusResponse`.
- Produces: `JobService.enqueue_search_index_rebuild() -> str`.
- Produces: `JobService.get_job_status(task_id: str) -> JobStatusResponse`.
- Produces: `get_job_service() -> JobService`.
- Produces: `GET /api/v1/jobs/{task_id}`.
- Replaces: synchronous `POST /api/v1/search/rebuild` with HTTP 202 enqueue behavior.

- [ ] **Step 1: Write failing job-service state tests**

Create `tests/unit/test_jobs.py`:

```python
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

    try:
        service.enqueue_search_index_rebuild()
    except JobEnqueueError as error:
        assert str(error) == "Could not enqueue background job."
    else:
        raise AssertionError("Expected broker failure to raise JobEnqueueError.")


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
```

- [ ] **Step 2: Run job-service tests and observe RED**

Run:

```bash
pytest tests/unit/test_jobs.py -v
```

Expected: collection fails because the job service does not exist.

- [ ] **Step 3: Implement job schemas and service**

Create `app/schemas/jobs.py`:

```python
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class JobAcceptedResponse(BaseModel):
    task_id: UUID
    status: str
    status_url: str


class JobStatusResponse(BaseModel):
    task_id: UUID
    status: str
    ready: bool
    successful: bool
    result: dict[str, Any] | None = None
    error: str | None = None
```

Create `app/services/jobs.py`:

```python
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
            result=task.result if is_success and isinstance(task.result, dict) else None,
            error="Background job failed." if task_state == states.FAILURE else None,
        )


def get_job_service() -> JobService:
    return JobService(rebuild_search_index_snapshot_task, celery_app.AsyncResult)
```

- [ ] **Step 4: Run job-service tests and observe GREEN**

Run:

```bash
pytest tests/unit/test_jobs.py -v
```

Expected: enqueue, success, and safe failure-state tests pass.

- [ ] **Step 5: Write failing API tests**

Create `tests/integration/test_job_api.py` with an injectable fake service:

```python
from uuid import UUID

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.schemas.jobs import JobStatusResponse
from app.services.search_index import SearchIndexService, get_search_index_service
from app.services.jobs import JobEnqueueError, get_job_service

TASK_ID = "c241dbf0-2d4e-4b91-9ad7-ce097a543bbd"


class EmptyScalarResult:
    def all(self):
        return []


class EmptySession:
    def scalars(self, statement):
        return EmptyScalarResult()


class FakeJobService:
    def __init__(self) -> None:
        self.enqueue_error: Exception | None = None
        self.requested_task_ids: list[str] = []

    def enqueue_search_index_rebuild(self) -> str:
        if self.enqueue_error:
            raise self.enqueue_error
        return TASK_ID

    def get_job_status(self, task_id: str) -> JobStatusResponse:
        self.requested_task_ids.append(task_id)
        return JobStatusResponse(
            task_id=UUID(task_id),
            status="SUCCESS",
            ready=True,
            successful=True,
            result={"index_version": f"redis-{task_id}", "document_count": 4},
        )


def build_client(service: FakeJobService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_job_service] = lambda: service
    app.dependency_overrides[get_db_session] = EmptySession
    app.dependency_overrides[get_search_index_service] = SearchIndexService
    return TestClient(app)


def test_search_rebuild_enqueues_job_and_returns_202():
    client = build_client(FakeJobService())

    response = client.post("/api/v1/search/rebuild")

    assert response.status_code == 202
    assert response.json() == {
        "task_id": TASK_ID,
        "status": "PENDING",
        "status_url": f"/api/v1/jobs/{TASK_ID}",
    }


def test_search_rebuild_maps_broker_failure_to_503():
    service = FakeJobService()
    service.enqueue_error = JobEnqueueError("Could not enqueue background job.")
    client = build_client(service)

    response = client.post("/api/v1/search/rebuild")

    assert response.status_code == 503
    assert response.json()["detail"] == "Could not enqueue background job."


def test_job_status_returns_normalized_result():
    service = FakeJobService()
    client = build_client(service)

    response = client.get(f"/api/v1/jobs/{TASK_ID}")

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert response.json()["result"]["document_count"] == 4
    assert service.requested_task_ids == [TASK_ID]


def test_job_status_rejects_malformed_uuid():
    response = build_client(FakeJobService()).get("/api/v1/jobs/not-a-uuid")

    assert response.status_code == 422
```

- [ ] **Step 6: Run API tests and observe RED**

Run:

```bash
pytest tests/integration/test_job_api.py -v
```

Expected: the enqueue response still has the old synchronous shape and `/jobs/{task_id}` returns 404.

- [ ] **Step 7: Implement the jobs router and asynchronous rebuild route**

Create `app/api/v1/jobs.py`:

```python
from uuid import UUID

from fastapi import APIRouter, Depends

from app.schemas.jobs import JobStatusResponse
from app.services.jobs import JobService, get_job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{task_id}", response_model=JobStatusResponse)
def get_job_status(
    task_id: UUID,
    service: JobService = Depends(get_job_service),
) -> JobStatusResponse:
    return service.get_job_status(str(task_id))
```

Register `jobs_router` in `app/api/v1/router.py`. Replace only the `rebuild_search_index` route in `app/api/v1/search.py`:

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
        task_id = service.enqueue_search_index_rebuild()
    except JobEnqueueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return JobAcceptedResponse(
        task_id=task_id,
        status="PENDING",
        status_url=f"/api/v1/jobs/{task_id}",
    )
```

Remove the rebuild route's now-unused SQLAlchemy session and `DocumentRepository` imports. Keep the search and explanation routes unchanged until Task 5.

- [ ] **Step 8: Verify Task 4 and commit**

Run:

```bash
pytest tests/unit/test_jobs.py tests/integration/test_job_api.py -v
git diff --check
```

Expected: job service and API tests pass.

Commit and push:

```bash
git add app/schemas/jobs.py app/services/jobs.py app/api/v1/jobs.py app/api/v1/router.py app/api/v1/search.py tests/unit/test_jobs.py tests/integration/test_job_api.py
git commit -m "feat: add background job api"
git push origin codex/task-1-scaffold
```

---

### Task 5: Search Route Activation, Documentation, And End-To-End Verification

**Files:**
- Modify: `app/api/v1/search.py`
- Modify: `tests/integration/test_search_api.py`
- Modify: `tests/integration/test_search_index_api_postgres.py`
- Modify: `docs/celery-worker.md`
- Modify: `docs/db-backed-search-index.md`
- Modify: `tests/unit/test_local_worker_setup.py`

**Interfaces:**
- Consumes: `get_synchronized_search_index_service()` from Task 2.
- Changes: `GET /api/v1/search` and `GET /api/v1/search/explain` synchronize from Redis before executing.
- Preserves: document writes still use the process-local `get_search_index_service()` dependency.

- [ ] **Step 1: Write a failing route dependency test**

Update `tests/integration/test_search_api.py` to override `get_synchronized_search_index_service` instead of `get_search_index_service`, then add a dependency-call assertion:

```python
from app.services.search_index_sync import get_synchronized_search_index_service


def test_search_route_uses_synchronized_index_dependency():
    app = create_app()
    search_index = SearchService.from_json_corpus("data/sample_corpus.json")
    calls = []

    def synchronized_index():
        calls.append("synchronized")
        return search_index

    app.dependency_overrides[get_synchronized_search_index_service] = synchronized_index
    client = TestClient(app)

    response = client.get("/api/v1/search", params={"q": "bm25"})

    assert response.status_code == 200
    assert calls == ["synchronized"]
```

In the existing `build_client`, override `get_synchronized_search_index_service` with the sample-corpus service so tests remain independent of Redis.

- [ ] **Step 2: Run the dependency test and observe RED**

Run:

```bash
pytest tests/integration/test_search_api.py::test_search_route_uses_synchronized_index_dependency -v
```

Expected: fail because the route still depends on `get_search_index_service`.

- [ ] **Step 3: Wire search and explanation to synchronized index dependency**

In `app/api/v1/search.py`, import `get_synchronized_search_index_service` and use it in the search and explanation parameters:

```python
search_index: SearchIndexService = Depends(get_synchronized_search_index_service)
```

Do not use the synchronized dependency in the rebuild route; rebuilding only enqueues Celery.

- [ ] **Step 4: Update live PostgreSQL test dependency boundaries**

In `tests/integration/test_search_index_api_postgres.py`, make both document writes and searches share the fixture's local index:

```python
app.dependency_overrides[get_search_index_service] = lambda: search_index
app.dependency_overrides[get_synchronized_search_index_service] = lambda: search_index
```

Remove `test_search_rebuild_loads_active_documents_from_postgres`; its synchronous contract was intentionally replaced and its asynchronous API behavior is covered in `tests/integration/test_job_api.py`. Remove imports that only supported that deleted test.

- [ ] **Step 5: Run route and PostgreSQL-marked tests**

Run:

```bash
pytest tests/integration/test_search_api.py tests/integration/test_job_api.py -v
pytest tests/integration/test_search_index_api_postgres.py -v
```

Expected: regular API tests pass; PostgreSQL-marked tests either pass with `RUN_POSTGRES_INTEGRATION=1` or report the existing intentional skip.

- [ ] **Step 6: Update worker and index documentation with exact commands**

Update `docs/celery-worker.md` and `docs/db-backed-search-index.md` to describe:

```text
POST /api/v1/search/rebuild
-> 202 Accepted with task_id and status_url
-> Redis broker
-> Celery loads PostgreSQL and publishes search:index:snapshot:{version}
-> Celery updates search:index:active_version
-> GET /api/v1/jobs/{task_id}
-> GET /api/v1/search activates the snapshot when its version changes
```

Also document that Celery's result backend currently reports an unknown valid
task UUID as `PENDING`; the planned PostgreSQL `jobs` table will later distinguish
unknown jobs and retain durable history.

Document these runnable commands exactly:

```bash
docker compose up -d postgres redis
alembic upgrade head
celery -A app.workers.celery_app.celery_app worker --loglevel=info
uvicorn app.main:app --reload
SEARCH_TASK_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/search/rebuild | python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')
curl "http://127.0.0.1:8000/api/v1/jobs/${SEARCH_TASK_ID}"
curl "http://127.0.0.1:8000/api/v1/search?q=bm25"
```

Update `tests/unit/test_local_worker_setup.py` to assert the docs contain `/api/v1/search/rebuild`, `/api/v1/jobs/`, and `search:index:active_version`.

- [ ] **Step 7: Run documentation and full automated verification**

Run:

```bash
pytest tests/unit/test_local_worker_setup.py -v
pytest -v
git diff --check
```

Expected: all non-live tests pass, live PostgreSQL tests retain only their environment-controlled skips, and the diff check exits `0`.

- [ ] **Step 8: Run live multi-process verification**

Start dependencies:

```bash
docker compose up -d postgres redis
docker compose ps
alembic upgrade head
```

Start the worker and API in separate terminal sessions:

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Submit and inspect the job:

```bash
SEARCH_TASK_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/search/rebuild | python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')
curl -i "http://127.0.0.1:8000/api/v1/jobs/${SEARCH_TASK_ID}"
curl "http://127.0.0.1:8000/api/v1/search?q=bm25"
```

Expected: rebuild returns `202`; status reaches `SUCCESS`; the status result and search response report the same `redis-{task_id}` index version. Stop the temporary worker and API sessions after verification.

- [ ] **Step 9: Commit and push the completed behavior**

Run:

```bash
git add app/api/v1/search.py tests/integration/test_search_api.py tests/integration/test_search_index_api_postgres.py docs/celery-worker.md docs/db-backed-search-index.md tests/unit/test_local_worker_setup.py
git commit -m "feat: activate redis search snapshots in api"
git push origin codex/task-1-scaffold
```

- [ ] **Step 10: Verify final repository state**

Run:

```bash
git status -sb
git log -5 --oneline --decorate
```

Expected: the worktree is clean and `codex/task-1-scaffold` matches `origin/codex/task-1-scaffold`.
