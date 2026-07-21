# Celery Worker

Celery is the background job layer. It lets slow work run outside FastAPI requests.

```text
FastAPI
  -> enqueue job
  -> Redis broker
  -> Celery worker
```

The `workers.ping` task checks the worker connection. Search-index rebuilds,
durable bulk document ingestion, and bounded Wikipedia category crawling run
through this layer.

## Start Redis

```bash
docker compose up -d redis
```

Check the container:

```bash
docker compose ps
```

## Start The Worker

Run this in a separate terminal:

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

## Send A Test Task

With Redis and the worker running:

```bash
celery -A app.workers.celery_app.celery_app call workers.ping
```

This enqueues the task and prints the task id. In the worker terminal, you should see the task execute.

## Background Search Index Rebuild

FastAPI enqueues the rebuild instead of loading PostgreSQL inside the request:

```text
POST /api/v1/search/rebuild
-> 202 Accepted with job_id and status_url
-> Redis broker
-> Celery loads PostgreSQL active documents
-> Celery validates the BM25/TF-IDF index
-> Celery writes search:index:snapshot:{version}
-> Celery updates search:index:active_version
-> GET /api/v1/jobs/{job_id}
-> GET /api/v1/search activates the snapshot when its version changes
```

The complete JSON snapshot is written before the active pointer. If indexing or
Redis publication fails, the previous pointer remains active and API processes
continue serving their last valid local index.

## Durable Bulk Ingestion

`POST /api/v1/documents/bulk` commits one PostgreSQL job and every raw input item
before it sends the job UUID to `documents.bulk_ingest`. The worker processes each
pending item in an independent transaction, records progress, and publishes one
snapshot when at least one document was imported.

The task uses late acknowledgement and worker-loss redelivery. A PostgreSQL
advisory lock prevents concurrent deliveries of the same job, while persisted
item statuses let a restarted delivery resume only unfinished items. Transient
PostgreSQL and Redis failures retry three times with bounded backoff.

See [Durable Bulk Document Ingestion](bulk-ingestion.md) for runnable requests and
the result contract.

## Wikipedia Category Crawls

The crawl endpoint commits a durable PostgreSQL job and sends its UUID to the
`wikipedia.crawl` task. The public job UUID and Celery task id are identical.
The task uses late acknowledgement and `reject_on_worker_lost`, so a worker
loss can redeliver the message. A PostgreSQL advisory lock prevents concurrent
deliveries from running the same crawl, and persisted frontier, page, and item
statuses let a redelivery resume safely.

Wikimedia request failures classified as transient, plus PostgreSQL and Redis
operational failures, retry with bounded backoff. A permanent page error is
recorded on that page and does not discard successful siblings. The worker
rebuilds and publishes one search snapshot after imported pages finish.

See [Wikipedia Category Crawler](wikipedia-crawler.md) for request bounds,
inspection endpoints, fake-Wikimedia verification, and the optional live smoke.

## Run The Complete Flow

Start PostgreSQL and Redis, then apply migrations:

```bash
docker compose up -d postgres redis
alembic upgrade head
```

Start the worker and API in separate terminals:

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

```bash
uvicorn app.main:app --reload
```

Submit a rebuild and capture its durable job id:

```bash
SEARCH_JOB_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/search/rebuild | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')
```

Inspect the job and then search the active snapshot:

```bash
curl "http://127.0.0.1:8000/api/v1/jobs/${SEARCH_JOB_ID}"
curl "http://127.0.0.1:8000/api/v1/search?q=bm25"
```

PostgreSQL is the job-status source of truth. Job and bulk-item history survives
Celery result expiry and Redis restarts, and an unknown valid job UUID returns
HTTP 404.

## Process Boundary

```text
Celery worker memory != FastAPI API memory
```

Redis bridges that boundary with a portable document snapshot. Celery publishes
the shared version; each FastAPI process rebuilds and atomically swaps its own
in-memory engine when it observes a newer version.

## Why Redis

Redis has three roles in this flow: broker queue, Celery result backend, and
versioned search snapshot store. PostgreSQL remains the source of truth for
documents and durable job history.
