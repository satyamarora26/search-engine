# Document API

The document API is the first HTTP layer that writes to PostgreSQL.

```text
FastAPI document route
  -> DocumentService
  -> DocumentRepository
  -> PostgreSQL documents table
```

## Endpoints

```text
POST   /api/v1/documents
GET    /api/v1/documents
GET    /api/v1/documents/{document_id}
PATCH  /api/v1/documents/{document_id}
DELETE /api/v1/documents/{document_id}
```

`DELETE` is a soft delete. The row remains in PostgreSQL, but its `status` changes from `active` to `deleted`, and normal reads stop returning it.

## Responsibilities

Routes handle HTTP concerns:

- request validation
- response status codes
- `404` for missing active documents
- `409` for duplicate URLs

`DocumentService` handles transaction boundaries:

- write succeeds -> `commit`
- write fails -> `rollback`
- read operations do not commit

`DocumentRepository` handles SQLAlchemy queries against the `documents` table.

## Why This Split Matters

Keeping these layers separate prevents route functions from becoming a mix of HTTP parsing, transaction handling, and SQL queries. Later, crawler ingestion and index refresh jobs can reuse the service or repository without pretending to be HTTP requests.
