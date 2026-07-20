# DB-Backed Search Index

Search now uses a mutable in-memory index that can be synchronized from PostgreSQL.

```text
PostgreSQL active documents
  -> SearchIndexService
  -> SearchEngine
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

## Rebuild Endpoint

The API also has:

```text
POST /api/v1/search/rebuild
```

This loads all active documents from PostgreSQL and rebuilds the in-memory index. That matters after a server restart, because the database persists but memory starts empty.

## Why This Comes Before Celery

This is the clean stepping stone before background indexing:

```text
Now:
DocumentService -> SearchIndexService

Later:
DocumentService -> queue job -> Celery worker -> SearchIndexService or persistent index
```

We get immediate search updates now without adding Redis/Celery complexity too early. Later, Celery can reuse the same indexing concepts for crawler ingestion.

## Celery Process Boundary

Celery runs in a separate worker process. That means a Celery task cannot directly mutate the FastAPI process's in-memory `SearchIndexService`.

The worker task `search.rebuild_index_snapshot` builds a worker-local index snapshot and returns stats. It is useful for proving that the worker can load active PostgreSQL documents and run indexing logic, but the API still uses `/api/v1/search/rebuild` for the API process's live in-memory index.
