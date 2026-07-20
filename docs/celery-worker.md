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

## Why Redis

Redis is the broker: it stores queued job messages until a Celery worker picks them up. The API should not perform slow crawler or indexing jobs inline, because that would make user requests slow and fragile.
