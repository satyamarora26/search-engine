# Durable Bulk Document Ingestion

Bulk ingestion accepts 1 to 500 raw JSON items, stores the job and every item in
PostgreSQL, and sends only the durable job UUID through Celery. Each item is then
validated and imported in its own transaction before one shared search snapshot
is published.

```text
FastAPI -> PostgreSQL job and raw items -> Redis broker -> Celery worker
        -> independent item outcomes -> one Redis search snapshot
```

## Start The Stack

Start PostgreSQL and Redis, then apply all migrations:

```bash
docker compose up -d postgres redis
alembic upgrade head
```

Run the worker and API in separate terminals:

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

```bash
uvicorn app.main:app --reload
```

## Submit A Batch

```bash
curl -X POST http://127.0.0.1:8000/api/v1/documents/bulk \
  -H 'Content-Type: application/json' \
  -d '{"documents":[{"title":"BM25","content":"BM25 ranking","url":"https://example.com/bm25-bulk"}]}'
```

A valid envelope returns HTTP `202`:

```json
{
  "job_id": "JOB_ID",
  "status": "PENDING",
  "status_url": "/api/v1/jobs/JOB_ID"
}
```

Use the returned UUID in both inspection endpoints:

```bash
curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID
curl 'http://127.0.0.1:8000/api/v1/documents/bulk/JOB_ID/items?limit=100&offset=0'
```

The item report is ordered by the original zero-based position. It contains only
`position`, `status`, `document_id`, and a safe `error`; it never returns the raw
document payload.

## Item Outcomes

Each submitted value reaches one terminal status:

- `imported`: a document was created and `document_id` identifies it.
- `skipped`: the URL already belongs to another document; error is
  `duplicate_url`.
- `failed`: validation or another safe document-integrity classification failed.

Invalid items do not reject a valid envelope. A mixed batch can therefore finish
successfully with imported, skipped, and failed siblings. `title` and `content`
must be nonblank strings; `url` is optional. Unknown fields fail only that item.
Null characters are valid in a staged JSON value but are not valid PostgreSQL
document text, so a title, content, or URL containing one receives a safe failed
item outcome without rolling back valid siblings.

## Progress And Results

For `N` submitted items, `progress.total` is `N + 1`. The first `N` units track
terminal item outcomes and the last unit tracks search-index publication or the
decision that no rebuild is required.

A successful job stores this summary:

```json
{
  "received_count": 3,
  "imported_count": 1,
  "skipped_count": 1,
  "failed_count": 1,
  "index_rebuilt": true,
  "index_version": "redis-JOB_ID"
}
```

When no item is imported, the worker keeps the active snapshot version and sets
`index_rebuilt` to `false`.

## Concurrency And Retries

Search rebuilds and bulk ingestion both mutate the shared search index. Only one
of these jobs may be `PENDING` or `STARTED`; a competing request returns HTTP
`409` with the active job ID and status URL.

The public job UUID is also the Celery task ID. A PostgreSQL advisory lock prevents
two deliveries from running the same bulk job concurrently. Celery acknowledges
the task late and permits redelivery after worker loss. PostgreSQL operational
errors and Redis connection or timeout errors retry at 2, 4, and 8 seconds. Other
errors fail immediately, and exhausted retries store `Bulk ingestion failed.`

API responses and durable rows contain sanitized errors. Full exception details
remain in server logs.

## Retention And Limits

Version 1 retains job rows, item payloads, item outcomes, and snapshots
indefinitely. Automatic pruning, payload compression, cancellation, idempotency
keys, and transactional-outbox recovery are later operational milestones.

PostgreSQL and Redis do not share one transaction. A process crash after the API
commit but before broker enqueue can leave a job pending; the API records a safe
failure when the broker call itself reports an error.
