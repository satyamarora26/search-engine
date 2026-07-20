# Durable Job Tracking

PostgreSQL stores background-job identity, state, progress, results, and safe
errors. Redis still transports Celery messages and stores versioned search
snapshots, but job history does not depend on Redis result expiry.

## Lifecycle

```text
PENDING -> STARTED -> SUCCESS
                   -> FAILURE
PENDING ----------------> FAILURE
```

Only one search-index rebuild may be pending or running. Repeated rebuild
requests return the existing active job.

## Start The Services

```bash
docker compose up -d postgres redis
alembic upgrade head
celery -A app.workers.celery_app.celery_app worker --loglevel=info
uvicorn app.main:app --reload
```

Run the worker and API commands in separate terminals.

## Rebuild And Inspect

```bash
SEARCH_JOB_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/search/rebuild | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')
curl "http://127.0.0.1:8000/api/v1/jobs/${SEARCH_JOB_ID}"
```

Progress advances through document loading, index building, snapshot publication,
and successful completion. Unknown valid UUIDs return HTTP 404.

## Failure Safety

The API and job row contain sanitized errors. Detailed exceptions remain in the
worker or API logs. Failed rebuilds do not replace the active Redis snapshot.

PostgreSQL and Redis do not share a transaction. A process crash after committing
a pending row but before sending its Celery message can leave that row pending.
Transactional outbox dispatch and stale-job recovery are deferred until the
project needs that operational complexity.
