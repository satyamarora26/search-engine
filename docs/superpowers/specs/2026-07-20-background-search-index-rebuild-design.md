# Background Search Index Rebuild Design

Date: 2026-07-20

## Goal

Replace the synchronous search-index rebuild endpoint with a real Celery job. The
worker will publish a versioned document snapshot to Redis, and every FastAPI
process will automatically activate the newest snapshot before searching.

The result must change the index used by live search rather than only building an
index inside Celery worker memory.

## Scope

This slice includes:

- Asynchronous `POST /api/v1/search/rebuild` behavior.
- Generic `GET /api/v1/jobs/{task_id}` status lookup.
- A versioned, JSON-encoded search document snapshot in Redis.
- Celery publication of a new active snapshot after successful validation.
- Lazy FastAPI synchronization when the active Redis version changes.
- Unit and API tests that do not require a live worker.
- Live verification with PostgreSQL, Redis, and a Celery worker.

This slice does not include:

- PostgreSQL job-history records.
- Progress percentages for index rebuilds.
- Automatic background indexing after every document write.
- Compiled inverted-index serialization.
- Snapshot retention or cleanup policies.

Document writes may continue to update the current FastAPI process immediately.
Other API processes become consistent after a background full rebuild publishes a
new snapshot.

## Chosen Architecture

Redis stores a portable document snapshot, not Python objects or private search
engine internals. A snapshot contains the source documents needed to rebuild the
pure-Python `SearchEngine` and an explicit format version.

Celery remains responsible for expensive database loading and validation. Each
FastAPI process rebuilds its local in-memory engine once when it observes a newer
active snapshot version. Normal searches only require a small Redis version read;
the complete snapshot is fetched only when the version changes.

This approach is preferred over serializing the compiled inverted index because
JSON documents are stable, inspectable, language-independent, and safe to decode.
Compiled-index serialization can be added later if benchmarks show local snapshot
activation is too expensive.

## Components

### Redis Search Index Store

A focused store owns Redis key construction, JSON encoding, publication, and
loading. Search and API layers do not issue raw Redis commands.

The keys are:

```text
search:index:snapshot:{version}
search:index:active_version
```

The snapshot payload is:

```json
{
  "format_version": 1,
  "index_version": "redis-<task-id>",
  "documents": [
    {
      "id": 42,
      "title": "Machine Learning",
      "content": "Machine learning is a field of artificial intelligence.",
      "url": "https://example.com/machine-learning"
    }
  ]
}
```

Publication writes the immutable snapshot key first and updates the active-version
pointer only after the snapshot write succeeds. A worker crash before pointer
publication leaves an unused snapshot but never exposes incomplete data. Updating
the pointer is a single atomic Redis operation.

Snapshot decoding validates the payload through Pydantic models. Pickle is not
used because decoding untrusted pickle data can execute code and because pickle
would tightly couple Redis data to Python class implementations.

### Celery Rebuild Task

`search.rebuild_index_snapshot` becomes a bound Celery task so its task id can be
used to derive a unique index version:

```text
redis-{celery_task_id}
```

The task performs these steps:

1. Open a SQLAlchemy session.
2. Load all active documents from PostgreSQL.
3. Build a temporary `SearchIndexService` to validate analyzer and index creation.
4. Convert the documents to the explicit snapshot schema.
5. Publish the snapshot and active version through the Redis store.
6. Return `index_version` and `document_count` as the Celery result.
7. Close the database session in all success and failure paths.

If database loading, index construction, encoding, or Redis publication fails,
the task fails and the previous active-version pointer remains unchanged.

### FastAPI Index Synchronization

The process-local `SearchIndexService` keeps its current `index_version`. Before a
search or explanation request, a synchronization service reads the Redis active
version.

If the versions match, it returns the existing service immediately. If they
differ, it loads and validates the active snapshot, builds a replacement engine,
and swaps the engine, document map, and index version under the existing lock.
Search requests therefore see either the complete old index or the complete new
index, never a partially rebuilt index.

If Redis is unavailable but the process already has an index, search fails open by
using that last known local index. If no active Redis snapshot exists, the current
local index is also used. Invalid or missing data for a published active version is
treated as a synchronization error and must not replace the working local index.

### Job API

`POST /api/v1/search/rebuild` no longer reads PostgreSQL or mutates process memory.
It enqueues `search.rebuild_index_snapshot` and returns HTTP `202 Accepted`:

```json
{
  "task_id": "c241dbf0-2d4e-4b91-9ad7-ce097a543bbd",
  "status": "PENDING",
  "status_url": "/api/v1/jobs/c241dbf0-2d4e-4b91-9ad7-ce097a543bbd"
}
```

`GET /api/v1/jobs/{task_id}` reads Celery's result backend and normalizes the
response:

```json
{
  "task_id": "c241dbf0-2d4e-4b91-9ad7-ce097a543bbd",
  "status": "SUCCESS",
  "ready": true,
  "successful": true,
  "result": {
    "index_version": "redis-c241dbf0-2d4e-4b91-9ad7-ce097a543bbd",
    "document_count": 125
  },
  "error": null
}
```

The public states are `PENDING`, `STARTED`, `RETRY`, `SUCCESS`, and `FAILURE`.
Unexpected Celery states are returned unchanged so operational information is not
discarded. `result` is present only for successful tasks. Failed tasks return the
stable message `Background job failed.` rather than raw exception text that could
contain database or infrastructure details.

Celery configuration enables `task_track_started`, allowing a worker that has
accepted a rebuild to report `STARTED` instead of remaining `PENDING` until the
task finishes.

Celery's result backend reports an unknown task id as `PENDING`. The API documents
this temporary ambiguity. A later PostgreSQL `jobs` table will provide existence
checks, durable history, progress counters, and safer expiry behavior.

## Dependencies And Testability

FastAPI dependencies provide the enqueue operation, Celery result lookup, Redis
store, and index synchronizer. Tests override these dependencies with fakes, so
API tests never require a running Redis server or Celery worker.

The Redis store accepts an injected Redis-compatible client. The Celery task's
plain helper accepts injected session and store factories. This keeps database,
Redis, task orchestration, and HTTP behavior independently testable.

## Error Handling

- Broker failure during enqueue returns HTTP `503 Service Unavailable` with a
  stable message.
- A malformed task id returns HTTP `422 Unprocessable Entity` through UUID path
  validation.
- Redis synchronization failure logs a warning, preserves the last valid local
  index, and allows search to continue with that index.
- Snapshot validation failure logs a warning, never mutates the local index, and
  allows search to continue with that index.
- Worker failure preserves the previous Redis active-version pointer.
- Job failure details remain in worker logs; the API returns a safe stable error.

## Testing Strategy

Unit tests cover:

- Snapshot JSON round trips, nullable URLs, and schema validation.
- Snapshot publication ordering and active-version loading.
- Worker publication after successful PostgreSQL loading and index validation.
- Database session closure and absence of pointer changes on worker failure.
- No-op synchronization when local and Redis versions match.
- Atomic local activation when a newer valid snapshot exists.
- Preservation of the local index when Redis or snapshot validation fails.
- Celery state normalization for pending, running, successful, and failed jobs.

FastAPI integration tests cover:

- Rebuild enqueue returns HTTP 202, task id, and status URL.
- Broker failure maps to HTTP 503.
- Job status returns normalized success and failure responses.
- The old synchronous rebuild behavior is no longer reachable.

Live verification covers:

1. Start PostgreSQL and Redis with Docker Compose.
2. Apply Alembic migrations and ensure active documents exist.
3. Start a Celery worker.
4. Enqueue `POST /api/v1/search/rebuild`.
5. Poll `GET /api/v1/jobs/{task_id}` until `SUCCESS`.
6. Confirm a search response reports the returned Redis index version.

## Acceptance Criteria

- `POST /api/v1/search/rebuild` returns in request time without building the
  index inline.
- A successful Celery task publishes a complete versioned snapshot to Redis.
- FastAPI automatically activates the latest valid snapshot before search.
- Failed rebuilds leave the previously active index available.
- Job status responses do not expose raw exception text.
- Focused tests, the full pytest suite, and the live service flow pass.
