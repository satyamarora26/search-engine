# DB-Backed Search Index

Search uses a mutable in-memory index synchronized through a versioned Redis
document snapshot. PostgreSQL remains the document source of truth.

```text
PostgreSQL active documents
  -> Celery rebuild task
  -> Redis versioned snapshot
  -> FastAPI SearchIndexSynchronizer
  -> process-local SearchIndexService
  -> /api/v1/search
```

## What Changed

Before this layer, `/api/v1/search` searched the sample JSON corpus.

Now, the search route uses `SearchIndexService`, an injectable singleton that owns the in-memory BM25/TF-IDF engine. Document writes update that index immediately:

```text
POST /api/v1/documents
  -> commit document to PostgreSQL
  -> add document to SearchIndexService

PATCH /api/v1/documents/{id}
  -> commit document update
  -> replace that document in SearchIndexService

DELETE /api/v1/documents/{id}
  -> soft-delete document in PostgreSQL
  -> remove document from SearchIndexService
```

## Background Rebuild Endpoint

The rebuild endpoint is asynchronous:

```text
POST /api/v1/search/rebuild
-> HTTP 202 with job_id and status_url
```

The API request sends `search.rebuild_index_snapshot` through Redis. Celery loads
active documents from PostgreSQL, validates indexing, writes
`search:index:snapshot:{version}`, and then updates
`search:index:active_version`.

Check the result with:

```text
GET /api/v1/jobs/{job_id}
```

PostgreSQL stores the job lifecycle and progress independently from Celery's
expiring result backend. Repeated rebuild requests return the same active job,
and an unknown valid job UUID returns HTTP 404.

Before each search or explanation, FastAPI compares its local index version with
the Redis active version. A changed version loads the JSON snapshot, builds a
replacement engine, and swaps the engine, document map, and version together.

## Consistency Model

```text
Document write in one API process
-> immediate local index update

Background full rebuild
-> all API processes observe the new Redis version
-> each process activates the same snapshot on its next search
```

Automatic per-document background indexing is a later slice. Until then, a full
background rebuild makes database-only changes visible across API processes.

## Celery Process Boundary

Celery cannot directly mutate FastAPI memory. Redis solves the boundary without
serializing Python objects or private inverted-index structures: the worker
publishes validated JSON documents and a version pointer, while FastAPI rebuilds
the custom BM25/TF-IDF engine locally.

If Redis is unavailable or a published snapshot is invalid, synchronization logs
the problem and preserves the last valid local index.
