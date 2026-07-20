# PostgreSQL Document Storage Design

## Goal

Introduce PostgreSQL as the future source of truth for searchable documents. This checkpoint creates the database foundation: configuration, SQLAlchemy base/session setup, the `documents` table model, and an Alembic migration.

## Current State

The API currently loads documents from:

```text
data/sample_corpus.json
```

That is good for learning and deterministic tests, but it is not persistent storage. PostgreSQL is the next layer because crawler output, manually created documents, index versions, and background jobs need a durable source of truth.

## Decision

Use SQLAlchemy 2.x models and Alembic migrations with PostgreSQL as the product database.

Local environment note: this machine currently does not have `psql`, Docker, or a running PostgreSQL server. This checkpoint will still be PostgreSQL-first, but verification will focus on model metadata, PostgreSQL dialect SQL compilation, config behavior, and existing app tests. Live database integration will require a PostgreSQL server or Docker in the next setup step.

## Document Table

The first persistent table is:

```text
documents
```

Columns:

```text
id          bigint identity primary key
title       text not null
url         text unique null
content     text not null
status      text not null default 'active'
created_at  timestamptz not null default now()
updated_at  timestamptz not null default now()
```

Constraints:

```text
documents_url_key unique(url)
documents_status_check status in ('active', 'deleted')
```

Indexes:

```text
documents_status_created_at_idx on (status, created_at)
documents_active_url_idx on (url) where status = 'active' and url is not null
```

Why:

- `bigint` is safer than `int` for growth.
- lowercase snake_case names work naturally with PostgreSQL and ORMs.
- `text` avoids artificial length limits for document fields.
- `timestamptz` stores timezone-aware timestamps.
- `status` enables soft delete so deleted documents disappear from normal reads without losing history.
- URL uniqueness prevents duplicate crawled/manual documents.
- partial active URL index supports the common duplicate-check path for active documents.

## Data Flow Later

```text
POST /api/v1/documents
  -> DocumentService
  -> DocumentRepository
  -> PostgreSQL documents table
  -> later indexing job reads active documents
  -> SearchEngine rebuilds in-memory index
```

## Scope

This checkpoint does not add document CRUD API routes yet. It prepares the database foundation those routes will use.

Out of scope:

- document POST/GET/PUT/DELETE routes
- PostgreSQL container setup
- Redis
- Celery
- Wikipedia crawler
- search API reading from PostgreSQL

## Testing

Tests will verify:

- default `DATABASE_URL` is PostgreSQL + psycopg
- environment override works
- `Document` model maps to the `documents` table
- important columns, constraints, and indexes exist in SQLAlchemy metadata
- PostgreSQL dialect SQL compiles for the table
- existing search/API tests still pass
