# Celery Worker

Celery is the background job layer. It lets slow work run outside FastAPI requests.

```text
FastAPI
  -> enqueue job
  -> Redis broker
  -> Celery worker
```

For now, this is only the foundation. The first task is a tiny `workers.ping` health task. Later, Wikipedia crawling and heavier indexing work can run through this worker.

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

## Search Index Snapshot Task

The first real search-related background task is:

```bash
celery -A app.workers.celery_app.celery_app call search.rebuild_index_snapshot
```

This task loads active documents from PostgreSQL, builds a worker-local BM25/TF-IDF index, and returns index stats.

Important process boundary:

```text
Celery worker memory != FastAPI API memory
```

So this task proves the worker can load and index PostgreSQL documents, but it does not update the FastAPI process's in-memory search index. The API index is still rebuilt with:

```text
POST /api/v1/search/rebuild
```

Later, when we move to a persistent index or event-based indexing, Celery can update that shared store directly.

## Why Redis

Redis is the broker: it stores queued job messages until a Celery worker picks them up. The API should not perform slow crawler or indexing jobs inline, because that would make user requests slow and fragile.
