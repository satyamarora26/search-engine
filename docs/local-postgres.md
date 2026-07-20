# Local PostgreSQL

This project uses PostgreSQL as the real application database. The local setup is intentionally small: one Postgres container, one persistent Docker volume, and the same `DATABASE_URL` shape the FastAPI app already reads from `app/core/config.py`.

## Why Docker

Docker lets every developer run the same database version with the same credentials. That matters for our search engine because migrations, indexes, background ingestion, and future ranking data should behave the same on every machine.

We are using `postgres:16-alpine` instead of the floating `latest` tag so the database version does not silently change between study sessions.

## First Run

Create your local environment file:

```bash
cp .env.example .env
```

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Apply the database schema:

```bash
alembic upgrade head
```

The app will use this database URL:

```bash
postgresql+psycopg://search_engine:search_engine@localhost:5432/search_engine
```

## Daily Commands

Run the real PostgreSQL integration tests:

```bash
RUN_POSTGRES_INTEGRATION=1 pytest tests/integration/test_document_repository_postgres.py -v
RUN_POSTGRES_INTEGRATION=1 pytest tests/integration/test_document_api_postgres.py -v
RUN_POSTGRES_INTEGRATION=1 pytest tests/integration/test_search_index_api_postgres.py -v
```

Check container health:

```bash
docker compose ps
```

Stop the database but keep data:

```bash
docker compose down
```

Reset the database completely:

```bash
docker compose down -v
```

## What This Gives Us Next

After this, we can write integration tests that run against real Postgres. Then we will build document CRUD on top of SQLAlchemy sessions and later connect indexing/ingestion to persisted documents.
