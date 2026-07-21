# Bulk Document Ingestion Design

Date: 2026-07-21

## Goal

Add durable, asynchronous ingestion for batches of documents. A client submits a
bounded JSON batch, PostgreSQL stores the job and every input item, Celery imports
valid documents independently, and the search index is rebuilt once after the
batch finishes.

The feature must support partial success: one invalid document or duplicate URL
must not discard valid documents from the same batch. It also establishes reusable
document-ingestion boundaries for the later Wikipedia crawler.

## Scope

This slice includes:

- `POST /api/v1/documents/bulk` for batches containing 1 to 500 JSON values.
- Durable PostgreSQL staging for every submitted item.
- A Celery bulk-ingestion task that receives only the durable job id.
- Independent validation, insertion, and outcome tracking for each item.
- Duplicate-URL skipping without aborting the batch.
- Durable progress and a final summary through the existing jobs API.
- A paginated endpoint for inspecting item-level outcomes.
- One shared concurrency guard for all background jobs that publish search
  snapshots.
- One search-index rebuild after a changed batch.
- Bounded automatic retries for transient PostgreSQL and Redis failures.
- Unit, API, PostgreSQL integration, and live-service verification.

This slice does not include:

- File, CSV, or NDJSON uploads.
- Batches larger than 500 items.
- Job cancellation.
- A public manual retry endpoint.
- Scheduled retention or cleanup.
- Wikipedia fetching or crawler orchestration.
- Query caching, operational endpoints, or frontend work.

Jobs and staged ingestion items remain stored indefinitely in v1 for auditability.
A retention policy can be added after the core backend is complete and real volume
is understood.

## Considered Approaches

### PostgreSQL staging plus Celery

The API stores the job and raw items in PostgreSQL, commits them together, and
sends only the job UUID to Celery. The worker can resume from pending items after
a transient failure, item-level results remain inspectable, and the later crawler
can reuse the same ingestion components.

This approach adds a migration, repository, and worker orchestration code, but it
is the selected design because durability and observable partial success are core
requirements.

### Full batch in the Celery message

The API could validate the request and send all documents through the Redis
broker. This requires less persistence code, but message size grows with document
content, submitted data is harder to inspect or recover, and retries depend more
heavily on broker retention. This approach is rejected.

### Synchronous API ingestion

The API could insert documents and rebuild the index before returning. The flow
is straightforward, but large requests would occupy API workers, risk request
timeouts, and provide poor progress visibility. This approach is rejected.

## Chosen Architecture

PostgreSQL is the source of truth for the batch, item outcomes, documents, and job
lifecycle. Redis remains the Celery broker/result backend and versioned search
snapshot store.

The API creates a `bulk_document_ingestion` job and its ingestion items in one
database transaction. Celery receives the same UUID used by the public job and
the PostgreSQL job row:

```text
PostgreSQL job id = public API job id = Celery task id
```

The worker loads staged items in request order. It validates and imports each
pending item in a short transaction, records progress, and continues after
item-level validation or duplicate errors. Once all items have terminal outcomes,
the worker rebuilds and publishes one versioned search snapshot if at least one
document was imported.

## Shared Index-Job Concurrency

Bulk ingestion changes PostgreSQL documents before publishing a new search
snapshot. It must not overlap a manual rebuild or the later crawler because an
older, slower task could otherwise publish a stale snapshot last. This guard
serializes background snapshot publishers; ordinary document CRUD keeps its
existing process-local update and eventual-consistency behavior.

Add a nullable `resource_key` column to `jobs`. Every job that can publish the
search index uses:

```text
resource_key = 'search_index'
```

A PostgreSQL partial unique index enforces one active owner:

```text
UNIQUE (resource_key)
WHERE resource_key IS NOT NULL
  AND status IN ('PENDING', 'STARTED')
```

The existing search rebuild job is migrated to this resource key, and its current
job-type-specific active-job index is removed. Terminal jobs do not hold the
resource.

Repeated manual rebuild requests remain idempotent: when the active owner is
another `search_index_rebuild`, the API returns that job with HTTP `202`. A manual
rebuild blocked by a different job type returns HTTP `409`.

Every bulk request contains distinct input, so a bulk request never reuses an
active job. If any search-index job is active, the bulk endpoint returns HTTP
`409 Conflict` with the active job id and status URL. The unique index is the final
guard when concurrent API processes race to create jobs.

## Data Model

### Jobs Extension

The `jobs` table gains:

| Column | Type | Rules |
| --- | --- | --- |
| `resource_key` | text | Nullable; `search_index` for index-publishing jobs |

The new migration backfills existing `search_index_rebuild` rows with
`search_index`, replaces the old partial unique index, and creates the shared
active-resource index.

The new job type constant is:

```text
bulk_document_ingestion
```

### Ingestion Items

The new `ingestion_items` table contains:

| Column | Type | Rules |
| --- | --- | --- |
| `id` | bigint identity | Primary key |
| `job_id` | PostgreSQL UUID | Required FK to `jobs.id`, cascade on job deletion |
| `position` | integer | Required zero-based request position |
| `payload` | JSON | Required original JSON value |
| `status` | text | `pending`, `imported`, `skipped`, or `failed` |
| `document_id` | bigint | Nullable FK to `documents.id` |
| `error` | text | Nullable safe item-level reason |
| `created_at` | timestamptz | Required, database-generated |
| `updated_at` | timestamptz | Required, changed with the outcome |

`(job_id, position)` is unique. Check constraints enforce the status values,
non-negative positions, and coherent terminal data:

- `pending` has no document id or error.
- `imported` has a document id and no error.
- `skipped` and `failed` have an error and no document id.

The original payload is retained for worker validation and future diagnosis.
PostgreSQL `json` is intentional: unlike `jsonb`, it can preserve a valid JSON
`\u0000` escape until worker validation classifies that item safely. The
item-results API does not return full content, avoiding unnecessarily large
responses.

## Request Validation

The request envelope is:

```json
{
  "documents": [
    {
      "title": "Information retrieval",
      "content": "Information retrieval finds relevant material...",
      "url": "https://example.com/information-retrieval"
    }
  ]
}
```

Envelope validation happens synchronously. `documents` must be a JSON array with
1 to 500 entries. Invalid JSON, a missing or non-array `documents` field, an empty
array, or more than 500 entries returns HTTP `422`; no job is created.

Array entries are staged as raw JSON values so one malformed item does not reject
the other entries. Worker-side item validation requires:

- An object containing only `title`, `content`, and optional `url` fields.
- Non-empty string `title` and `content` after trimming.
- A string, null, or omitted `url`; blank URLs normalize to null.

A scalar, list, missing field, wrong field type, blank required value, or unknown
field becomes an item-level `failed` outcome. This split between envelope and item
validation is intentional and is what enables partial success.

## Components

### Ingestion Item Repository

The repository owns staging, ordered loading, outcome transitions, counts, and
paginated item queries. It contains no HTTP, Celery, or search-index logic.

State changes include `status = 'pending'` in their conditions. Retried tasks
therefore cannot overwrite terminal outcomes. The caller owns commits and
rollbacks.

### Document Importer

A focused importer validates one raw payload and inserts one document. It returns
a typed outcome instead of raising for expected item problems:

```text
imported -> created document id
skipped  -> duplicate_url
failed   -> safe validation reason
```

Only non-null URLs participate in duplicate detection, matching the current
`documents.url` unique constraint. Multiple documents without URLs are valid.
The insert and item-outcome update occur in the same transaction, so a retry
cannot duplicate a successfully imported URL-less document.

This component is independent of the bulk API and Celery task so the Wikipedia
crawler can reuse the same validation and duplicate behavior later.

### Bulk Ingestion Service

The API-facing service:

1. Checks for an active `search_index` resource owner.
2. Generates one UUID.
3. Creates the pending bulk job with total progress `item_count + 1`.
4. Stages all raw items with their original positions.
5. Commits the job and items atomically.
6. Sends the Celery task with the UUID as both argument and task id.
7. Returns the durable job.

If the shared-resource unique index loses a race, the transaction rolls back and
the service raises a conflict containing the winning active job. No submitted
items from the losing request are staged.

As with the existing rebuild flow, PostgreSQL and Redis cannot be committed
atomically. A normal broker-send failure marks the job `FAILURE` with a safe
message and returns HTTP `503`; staged items remain available for diagnosis. A
process crash between the database commit and broker send can still leave a stale
pending job. A transactional outbox remains outside this slice.

### Bulk Celery Task

The bound task verifies that its Celery request id equals the durable job id. On
the first attempt it claims the pending job. A Celery retry with the same task id
may resume a started job. A redelivery that finds a terminal job performs no
ingestion or publication; a successful redelivery returns the stored result.

The task uses late acknowledgement and worker-loss rejection so a worker crash
can redeliver the durable job. A PostgreSQL advisory lock scoped to the job UUID
ensures only one delivery executes that job at a time; the connection releases
the lock automatically if the worker dies.

The task processes pending items by ascending position. Each item uses its own
transaction, atomically inserting the document and recording `imported`, or
recording the expected `skipped`/`failed` outcome. Progress is persisted after
each item.

After every item is terminal:

- If at least one item was imported, build and publish `redis-<job-id>` once.
- If no item was imported, keep the current active index and skip rebuilding.
- Mark the job successful with the final summary.

A batch is successfully processed even when every item is skipped or fails
validation. `SUCCESS` describes completion of the batch workflow; item counts
describe the data outcomes.

## Progress And Result

For `N` items, progress has total `N + 1`:

```text
PENDING  0/(N+1)  Waiting for worker
STARTED  0/(N+1)  Processing documents
STARTED  1/(N+1)  Processed document 1 of N
...
STARTED  N/(N+1)  Rebuilding search index
SUCCESS  (N+1)/(N+1)  Bulk ingestion completed
```

When no document was imported, the last step reports `No index changes required`
before successful completion.

The success result stored in `jobs.result` is:

```json
{
  "received_count": 3,
  "imported_count": 1,
  "skipped_count": 1,
  "failed_count": 1,
  "index_rebuilt": true,
  "index_version": "redis-<job-id>"
}
```

`index_version` is the unchanged active version, or null when no active version
exists, if rebuilding was unnecessary.

## Retry And Failure Handling

Expected item errors never retry the task:

- Invalid item shape or fields becomes `failed` with a safe validation reason.
- A duplicate non-null URL becomes `skipped` with `duplicate_url`.
- Another item-specific integrity violation becomes `failed` with a stable safe
  reason.

Transient PostgreSQL connection/operational errors and Redis connection errors
retry the Celery task up to three times with increasing delays. Terminal items
are skipped on retry, pending items resume in order, and the job remains `STARTED`
with a safe retry progress message. If retries are exhausted, the job becomes
`FAILURE`. This retry policy applies to the new bulk task; the existing manual
rebuild task keeps its previously designed no-automatic-retry behavior.

Unexpected programming or invariant errors do not retry indefinitely. The worker
logs the original exception, marks the job failed with a stable public error, and
re-raises so Celery also records failure.

If documents were inserted but Redis publication ultimately fails, PostgreSQL
remains authoritative and the previously active Redis snapshot remains usable.
The failed job and item outcomes make the partial state visible. A later manual
search rebuild publishes all active PostgreSQL documents.

Raw database, broker, Redis, and stack-trace details are never stored in public
job or item error fields.

If PostgreSQL remains unavailable when the worker tries to record final failure,
the durable job can remain `STARTED`; Celery and worker logs still record the task
failure. General stale-job reconciliation remains deferred with the existing job
tracking design.

## API Contract

### Submit A Batch

`POST /api/v1/documents/bulk` returns HTTP `202 Accepted`:

```json
{
  "job_id": "57d89fd9-4b92-468c-8cc4-640ce73ec4f1",
  "status": "PENDING",
  "status_url": "/api/v1/jobs/57d89fd9-4b92-468c-8cc4-640ce73ec4f1"
}
```

When another search-index-changing job is active, it returns HTTP `409 Conflict`:

```json
{
  "detail": {
    "message": "A search index job is already active.",
    "active_job_id": "d58af7e4-a17c-49a2-b5d7-cb00abf7eb26",
    "status_url": "/api/v1/jobs/d58af7e4-a17c-49a2-b5d7-cb00abf7eb26"
  }
}
```

### Inspect Item Outcomes

`GET /api/v1/documents/bulk/{job_id}/items?limit=100&offset=0` returns:

```json
{
  "job_id": "57d89fd9-4b92-468c-8cc4-640ce73ec4f1",
  "total_results": 3,
  "limit": 100,
  "offset": 0,
  "items": [
    {
      "position": 0,
      "status": "imported",
      "document_id": 81,
      "error": null
    },
    {
      "position": 1,
      "status": "skipped",
      "document_id": null,
      "error": "duplicate_url"
    },
    {
      "position": 2,
      "status": "failed",
      "document_id": null,
      "error": "content must be a non-empty string"
    }
  ]
}
```

The endpoint accepts `limit` from 1 to 100 and a non-negative `offset`. A known
non-bulk job id or unknown valid UUID returns HTTP `404`; malformed UUIDs return
HTTP `422`.

The existing `GET /api/v1/jobs/{job_id}` endpoint exposes durable progress and the
summary result without requiring a new job-status contract.

## Data Flow

```text
Client
  -> POST /api/v1/documents/bulk
  -> validate envelope
  -> create PENDING job and stage every item in one PostgreSQL transaction
  -> enqueue Celery task using the same UUID
  -> return 202 with job id
  -> worker claims the job and processes pending items independently
  -> worker records item outcomes and progress
  -> worker rebuilds and publishes one Redis snapshot when data changed
  -> worker records SUCCESS and summary in PostgreSQL
  -> client reads job status and paginated item outcomes
```

## Testing Strategy

Unit tests cover:

- Envelope limits and worker-side item validation.
- Imported, duplicate, invalid, and URL-less item outcomes.
- Atomic document/item writes and retry idempotency.
- Ordered progress, counts, no-change behavior, and final result shape.
- Transient retry classification, retry exhaustion, and safe errors.
- One task id shared across API, PostgreSQL, and Celery.
- Advisory-lock handling and duplicate-delivery protection.

FastAPI tests cover:

- A valid batch returns HTTP `202` and stages every item.
- Invalid envelopes return HTTP `422` without creating a job.
- Active index jobs return HTTP `409` with the active job reference.
- Paginated item outcomes and bulk-only job lookup behavior.
- Broker failure marks the durable job failed and returns HTTP `503`.

PostgreSQL integration tests cover:

- Migration upgrade and downgrade.
- Shared resource uniqueness across rebuild and bulk job types.
- Concurrent job-creation race handling.
- Ingestion-item constraints, ordering, transitions, and counts.
- Duplicate URLs already in PostgreSQL and repeated within one batch.
- Partial success committed across independent item transactions.

Live-service verification runs PostgreSQL, Redis, an API process, and a Celery
worker, then submits a mixed batch, polls the durable job, checks item outcomes,
searches for the imported document, and confirms only one new active snapshot was
published. The complete existing pytest suite must also pass.

## Success Criteria

The milestone is complete when:

- A client can submit 1 to 500 JSON items without placing document content in the
  Celery message.
- Valid documents survive invalid and duplicate siblings in the same batch.
- Every item has a durable, inspectable terminal outcome after successful job
  completion.
- Progress and summary counts remain correct across transient retries.
- Competing index-changing jobs cannot publish snapshots concurrently.
- A changed batch publishes exactly one new versioned snapshot.
- Search returns newly imported documents after the job succeeds.
- Unit, API, PostgreSQL integration, live-service, and regression tests pass.
