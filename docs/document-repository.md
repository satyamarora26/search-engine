# Document Repository

The `DocumentRepository` is the first database access layer for the `documents` table.

For now, it is intentionally separate from FastAPI routes:

```text
future API route or service
  -> SQLAlchemy Session
  -> DocumentRepository
  -> PostgreSQL documents table
```

## Why A Repository

Without a repository, database queries spread across API routes, services, crawler code, and indexing jobs. That becomes hard to test and hard to change.

The repository gives us one focused place for document persistence behavior:

- create an active document
- read only active documents
- list active documents in stable `id` order
- update only active documents
- soft-delete documents by changing `status` to `deleted`

## Transaction Boundary

The repository calls:

```python
session.flush()
session.refresh(document)
```

It does not call:

```python
session.commit()
session.rollback()
```

That is deliberate. The repository performs database operations, but the outer layer should decide whether the whole request or background job succeeds. Later, the FastAPI document routes will commit after a successful operation and rollback on errors.

## Soft Delete

We do not physically remove rows from the `documents` table yet. Instead:

```text
active -> deleted
```

Normal reads filter by `status = 'active'`, so deleted documents disappear from the app while still leaving history available for debugging or future admin tools.
