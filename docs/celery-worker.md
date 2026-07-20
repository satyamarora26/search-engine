# Celery Worker

Celery is the background job layer. It lets slow work run outside FastAPI requests.

```text
FastAPI
  -> enqueue job
  -> Redis broker
  -> Celery worker
```

The `workers.ping` task checks the worker connection. Search-index rebuilds are the
first production workflow running through this layer; Wikipedia crawling and bulk
ingestion will use the same pattern later.

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
-> 202 Accepted with task_id and status_url
-> Redis broker
-> Celery loads PostgreSQL active documents
-> Celery validates the BM25/TF-IDF index
-> Celery writes search:index:snapshot:{version}
-> Celery updates search:index:active_version
-> GET /api/v1/jobs/{task_id}
-> GET /api/v1/search activates the snapshot when its version changes
```

The complete JSON snapshot is written before the active pointer. If indexing or
Redis publication fails, the previous pointer remains active and API processes
continue serving their last valid local index.

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

Submit a rebuild and capture its task id:

```bash
SEARCH_TASK_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/search/rebuild | python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')
```

Inspect the job and then search the active snapshot:

```bash
curl "http://127.0.0.1:8000/api/v1/jobs/${SEARCH_TASK_ID}"
curl "http://127.0.0.1:8000/api/v1/search?q=bm25"
```

Celery's result backend reports an unknown valid task UUID as `PENDING`. The
planned PostgreSQL `jobs` table will later distinguish unknown jobs, retain
history, and store progress counters.

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
documents.
