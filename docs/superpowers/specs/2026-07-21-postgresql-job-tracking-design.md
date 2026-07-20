# PostgreSQL Job Tracking Design

Date: 2026-07-21

## Goal

Make background-job status durable and unambiguous by storing job records in
PostgreSQL. The search-index rebuild remains a Celery task, but PostgreSQL becomes
the source of truth for job identity, lifecycle, progress, results, and safe
failure messages.

This removes the current ambiguity where Celery reports both a real queued task
and an unknown or expired task id as `PENDING`. It also establishes the job model
that later bulk-ingestion and Wikipedia-crawler work can reuse.

## Scope

This slice includes:

- A PostgreSQL `jobs` table and Alembic migration.
- A SQLAlchemy job model and focused repository.
- Durable enqueue, lifecycle, progress, result, and failure records.
- One UUID shared by the API job, PostgreSQL row, and Celery task.
- PostgreSQL-backed `GET /api/v1/jobs/{job_id}` behavior.
- Duplicate suppression for active search-index rebuilds.
- Explicit lifecycle updates from the search rebuild worker.
- Unit, API, PostgreSQL integration, and live-service verification.

This slice does not include:

- Automatic Celery retries.
- Job cancellation or deletion.
- Job-listing or administrative endpoints.
- Stale-job recovery.
- A transactional outbox or broker dispatcher.
- Cleanup or retention jobs.
- Bulk ingestion or Wikipedia crawling.

Job records remain indefinitely during development. A retention policy can be
added when job volume makes cleanup necessary.

## Chosen Architecture

PostgreSQL is the durable job-status source of truth. Redis keeps its existing
roles as the Celery broker, Celery result backend, and versioned search-snapshot
store. The public job-status endpoint no longer calls `Celery.AsyncResult`.

The API generates a UUID before enqueueing and uses that value as:

```text
PostgreSQL job id = public API job id = Celery task id
```

Using one identity makes an API request, database row, worker log, Celery task,
and Redis index version directly traceable. The API calls it `job_id` so clients
are not coupled to Celery terminology.

Worker tasks update lifecycle state explicitly through the job repository. This
is preferred over Celery signals because the control flow remains visible,
job-specific progress is straightforward, and each transition can be unit tested.
Periodic synchronization from Celery results is rejected because it introduces
delay and still depends on expiring result-backend data.

## Data Model

The `jobs` table contains:

| Column | Type | Rules |
| --- | --- | --- |
| `id` | PostgreSQL UUID | Primary key; also used as Celery task id |
| `job_type` | text | Required; initially `search_index_rebuild` |
| `status` | text | `PENDING`, `STARTED`, `SUCCESS`, or `FAILURE` |
| `progress_current` | bigint | Required, defaults to `0`, cannot be negative |
| `progress_total` | bigint | Nullable; when present it is positive |
| `progress_message` | text | Nullable, short, and safe for API display |
| `result` | JSONB | Nullable; populated only on success |
| `error` | text | Nullable; sanitized and populated only on failure |
| `created_at` | timestamptz | Required, database-generated |
| `started_at` | timestamptz | Nullable; set on the successful worker claim |
| `finished_at` | timestamptz | Nullable; set on success or failure |
| `updated_at` | timestamptz | Required; changed on each lifecycle update |

Database check constraints enforce the allowed statuses and progress bounds.
When `progress_total` is present, `progress_current` cannot exceed it.

The following partial unique index permits only one active search-index rebuild:

```text
UNIQUE (job_type)
WHERE job_type = 'search_index_rebuild'
  AND status IN ('PENDING', 'STARTED')
```

The condition is deliberately specific to search rebuilds. Future job types can
choose their own concurrency policy instead of inheriting a global restriction.

No `ready` or `successful` columns are stored. They are derived when producing an
API response:

```text
ready      = status IN (SUCCESS, FAILURE)
successful = status = SUCCESS
```

## Components

### Job Model

The SQLAlchemy `Job` model defines the table, check constraints, partial unique
index, server-generated timestamps, and JSONB result. Model constants provide
stable job-type and status values without adding a database enum migration burden
at this stage.

### Job Repository

The repository owns persistence operations and contains no Celery or HTTP logic.
Its focused operations include:

- Create a pending job with a caller-provided UUID.
- Find a job by id.
- Find the active search-index rebuild.
- Atomically claim a pending job by changing it to `STARTED`.
- Update progress for a started job.
- Mark a started job `SUCCESS` with a JSON result.
- Mark a pending or started job `FAILURE` with a safe error.

State-changing statements include their expected current status in the `WHERE`
clause. The affected-row count determines whether the transition succeeded. This
prevents duplicate task delivery or stale worker updates from overwriting a newer
or terminal state.

The repository flushes changes, while the calling service controls commits and
rollbacks. Worker progress updates use separate short transactions so another
process can observe them while the rebuild continues.

### Job Service

The service coordinates API-facing behavior:

1. Look for an active search-index rebuild.
2. Return it when one already exists.
3. Otherwise generate a UUID and commit a `PENDING` job.
4. Enqueue Celery with `apply_async(task_id=str(job.id), args=[str(job.id)])`.
5. Return the durable job record.

The PostgreSQL unique index is the final concurrency guard. If two API processes
race to insert, the process that loses the unique-index race rolls back, loads the
winning active job, and returns it.

### Celery Rebuild Task

The bound Celery task accepts the job UUID and verifies that it matches the
Celery request id. It atomically claims the `PENDING` job before doing expensive
work. If the row does not exist or is no longer pending, the task does not rebuild
or publish a snapshot.

The successful progress sequence is:

```text
PENDING  0/4  Waiting for worker
STARTED  1/4  Loading documents
STARTED  2/4  Building search index
STARTED  3/4  Publishing search snapshot
SUCCESS  4/4  Search index rebuilt
```

On success, the JSONB result is:

```json
{
  "index_version": "redis-<job-id>",
  "document_count": 125
}
```

On failure, the worker logs the original exception, attempts to mark the job
`FAILURE` with `Search index rebuild failed.`, and re-raises the original
exception so Celery also records failure. Database sessions close on every path.

## Data Flow

### New Rebuild

```text
Client
  -> POST /api/v1/search/rebuild
  -> JobService creates and commits PENDING job
  -> JobService sends Celery task with the same UUID
  -> API returns 202 with job id and status URL
  -> worker claims job as STARTED
  -> worker records progress in short transactions
  -> worker publishes the Redis snapshot
  -> worker records SUCCESS and result in PostgreSQL
  -> GET /api/v1/jobs/{job_id} returns the durable result
```

### Duplicate Rebuild Request

When a `PENDING` or `STARTED` search rebuild exists, the service returns that job
with HTTP `202` instead of enqueueing more work. This makes repeated requests
harmless and prevents an older, slower rebuild from publishing after a newer one.

### PostgreSQL And Broker Boundary

PostgreSQL and Redis cannot be committed atomically. The service commits the job
before sending the task because sending first could allow a fast worker to run
before the row exists. A normal broker submission failure is caught, the job is
marked `FAILURE` with `Could not enqueue background job.`, and the API returns
HTTP `503 Service Unavailable`.

A process crash exactly after the database commit and before broker submission
can leave a stale `PENDING` row. A transactional outbox would close this gap but
requires an outbox table and dispatcher process. That complexity is deferred.
Stale-job detection and recovery will be designed if operational testing shows it
is needed.

## API Contract

`POST /api/v1/search/rebuild` returns HTTP `202 Accepted` for a newly created job
or an already-active rebuild:

```json
{
  "job_id": "c241dbf0-2d4e-4b91-9ad7-ce097a543bbd",
  "status": "PENDING",
  "status_url": "/api/v1/jobs/c241dbf0-2d4e-4b91-9ad7-ce097a543bbd"
}
```

`GET /api/v1/jobs/{job_id}` returns PostgreSQL-backed state:

```json
{
  "job_id": "c241dbf0-2d4e-4b91-9ad7-ce097a543bbd",
  "job_type": "search_index_rebuild",
  "status": "STARTED",
  "ready": false,
  "successful": false,
  "progress": {
    "current": 2,
    "total": 4,
    "percentage": 50.0,
    "message": "Building search index"
  },
  "result": null,
  "error": null,
  "created_at": "2026-07-21T10:00:00Z",
  "started_at": "2026-07-21T10:00:01Z",
  "finished_at": null
}
```

Percentage is derived when a total is known and is otherwise `null`. A valid but
unknown UUID returns HTTP `404 Not Found`. A malformed UUID continues to return
HTTP `422 Unprocessable Entity` through FastAPI validation.

The response changes `task_id` to `job_id`. This project has no external API
consumers yet, and adopting domain terminology now prevents a lasting Celery
coupling in the public contract.

## State Transitions

Only these transitions are valid:

```text
PENDING -> STARTED
PENDING -> FAILURE
STARTED -> SUCCESS
STARTED -> FAILURE
```

`SUCCESS` and `FAILURE` are immutable terminal states. Progress updates are
accepted only for a `STARTED` job. Successful completion sets `result`, clears
`error`, advances progress to the total, and sets `finished_at`. Failure clears
`result`, stores a safe error, and sets `finished_at`.

Automatic retries are intentionally absent. A failed rebuild preserves the
previous active Redis search snapshot, and a client may request a new job. Retry
classification and exponential backoff will be designed with the Wikipedia
crawler, where transient network errors are a normal part of the workload.

## Error Handling

- PostgreSQL failure while creating a job returns HTTP `503`; no task is sent.
- Broker submission failure marks the durable job `FAILURE` and returns HTTP
  `503` with a stable message.
- A missing job or invalid worker claim prevents task execution and snapshot
  publication.
- Document loading or index construction failure marks the job `FAILURE` and
  leaves the previous Redis active-version pointer unchanged.
- Snapshot publication failure marks the job `FAILURE` and leaves the previous
  active snapshot available.
- A job-status database outage returns HTTP `503`, not a misleading `404`.
- A valid unknown job UUID returns HTTP `404`.
- Public responses and stored job errors never include raw database, Redis, or
  broker exception text.

If PostgreSQL becomes unavailable while the worker is recording failure, Celery
still stores task failure in its backend and worker logs contain both errors. The
job may remain `STARTED`; later stale-job recovery can reconcile such records.

## Testing Strategy

Unit tests cover:

- Job model defaults, constraints, and response derivation.
- Allowed and rejected lifecycle transitions.
- Progress bounds and percentage calculation.
- Enqueue with one UUID shared across the row and Celery task.
- Active-job reuse and unique-index race recovery.
- Worker progress ordering, successful result storage, and session closure.
- Worker failures, safe errors, and original exception re-raising.
- Duplicate delivery protection through conditional claiming.

FastAPI tests cover:

- A new rebuild returns HTTP `202`, `job_id`, and status URL.
- A repeated rebuild request returns the existing active job.
- A known job returns PostgreSQL-backed progress and result data.
- A valid unknown UUID returns HTTP `404`.
- A malformed UUID returns HTTP `422`.
- Database and broker failures return HTTP `503`.
- Raw infrastructure exception details never enter responses.

PostgreSQL integration tests cover:

- The migration creates the table, constraints, and indexes.
- Only one active search rebuild can exist at a time.
- A terminal job does not prevent a later rebuild.
- JSONB results round-trip correctly.
- Conditional state transitions are atomic.

Live verification covers:

1. Start PostgreSQL and Redis and apply Alembic migrations.
2. Start FastAPI and a Celery worker.
3. Enqueue a rebuild and observe durable progress.
4. Wait for `SUCCESS` and verify the stored result.
5. Confirm search activates the newly published snapshot.
6. Restart Redis and confirm PostgreSQL job history remains available.
7. Confirm an unknown UUID returns HTTP `404`.

## Acceptance Criteria

- PostgreSQL durably distinguishes existing jobs from unknown ids.
- One UUID traces a job across the API, PostgreSQL, Celery, logs, and snapshots.
- Only one active search-index rebuild can exist.
- Worker progress becomes observable through the job API.
- Terminal states cannot be overwritten by duplicate or stale updates.
- Successful jobs retain structured results after Celery result expiry.
- Failed jobs expose only sanitized errors and preserve the working search index.
- Existing tests, new focused tests, PostgreSQL integration tests, and the live
  service flow pass.
