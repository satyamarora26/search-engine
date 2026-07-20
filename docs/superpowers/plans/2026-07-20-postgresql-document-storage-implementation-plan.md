# PostgreSQL Document Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PostgreSQL-oriented database configuration, SQLAlchemy model metadata, and Alembic migration support for persistent documents.

**Architecture:** Keep database setup separate from HTTP routes. `app/core/config.py` owns environment-backed settings, `app/db/base.py` owns the SQLAlchemy declarative base, `app/db/session.py` owns engine/session creation, `app/models/document.py` maps the `documents` table, and Alembic owns schema migration files.

**Tech Stack:** SQLAlchemy 2.x, Alembic, PostgreSQL dialect, psycopg driver, pytest.

## Global Constraints

- PostgreSQL is the product database.
- Do not use SQLite as the product database.
- Local live PostgreSQL verification is deferred until a PostgreSQL server or Docker is available.
- Use lowercase snake_case table, column, constraint, and index names.
- Use `bigint` identity primary key.
- Use `text` for title, URL, content, and status.
- Use timezone-aware timestamps.
- Keep this checkpoint focused on database foundation only; do not add document CRUD API routes yet.
- Commit and push after verification.

---

### Task 1: Database Foundation And Document Model

**Files:**
- Modify: `requirements.txt`
- Create: `app/core/__init__.py`
- Create: `app/core/config.py`
- Create: `app/db/__init__.py`
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Create: `app/models/__init__.py`
- Create: `app/models/document.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/20260720_0001_create_documents.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/unit/test_document_model.py`

**Interfaces:**
- Produces: `get_settings() -> Settings`.
- Produces: `Base` SQLAlchemy declarative base.
- Produces: `SessionLocal`.
- Produces: `get_db_session() -> Generator[Session, None, None]`.
- Produces: `Document` SQLAlchemy model.

- [ ] **Step 1: Write failing config and model tests**

Create tests that assert:

```python
from app.core.config import DEFAULT_DATABASE_URL, get_settings

def test_default_database_url_uses_postgresql_psycopg(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = get_settings()

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.database_url.startswith("postgresql+psycopg://")
```

```python
def test_database_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://user:pass@localhost:5432/test_db"
```

```python
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.document import Document

def test_document_model_uses_documents_table():
    assert Document.__tablename__ == "documents"
    assert {"id", "title", "url", "content", "status", "created_at", "updated_at"} <= set(Document.__table__.columns.keys())
```

```python
def test_document_model_has_expected_constraints_and_indexes():
    constraint_names = {constraint.name for constraint in Document.__table__.constraints}
    index_names = {index.name for index in Document.__table__.indexes}

    assert "documents_url_key" in constraint_names
    assert "documents_status_check" in constraint_names
    assert "documents_status_created_at_idx" in index_names
    assert "documents_active_url_idx" in index_names
```

```python
def test_document_model_compiles_for_postgresql():
    sql = str(CreateTable(Document.__table__).compile(dialect=postgresql.dialect()))

    assert "CREATE TABLE documents" in sql
    assert "BIGINT" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
pytest tests/unit/test_config.py tests/unit/test_document_model.py -v
```

Expected: fail because config and model modules do not exist.

- [ ] **Step 3: Implement config, db base, session, and model**

Rules:

- add `psycopg[binary]` to `requirements.txt`
- `DEFAULT_DATABASE_URL` must be `postgresql+psycopg://search_engine:search_engine@localhost:5432/search_engine`
- `Document.id` must use `BigInteger` and `Identity`
- `Document.status` must default to `active`
- `Document.created_at` and `Document.updated_at` must be timezone-aware
- define URL unique constraint and status check constraint
- define status/created_at composite index
- define active URL partial index using PostgreSQL `WHERE status = 'active' and url is not null`

- [ ] **Step 4: Add Alembic config and migration**

Migration must create:

```text
documents table
documents_url_key unique constraint
documents_status_check check constraint
documents_status_created_at_idx index
documents_active_url_idx partial index
```

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
pytest tests/unit/test_config.py tests/unit/test_document_model.py -v
pytest tests/unit/search tests/integration tests/unit/test_config.py tests/unit/test_document_model.py -v
```

Expected:

```text
Config/model tests pass
Existing search and API tests still pass
```

- [ ] **Step 6: Commit and push**

Run:

```bash
git add requirements.txt app/core app/db app/models alembic alembic.ini tests/unit/test_config.py tests/unit/test_document_model.py
git commit -m "feat: add postgresql document storage foundation"
git push
```
