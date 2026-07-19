# Search Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. For this project, execute inline with the user because the goal is to learn and understand every part, not to have the agent build silently.

**Goal:** Build a backend-only search engine from scratch with FastAPI, PostgreSQL, Redis, Celery, inverted indexing, TF-IDF, BM25, tests, benchmarks, and placement-ready documentation.

**Architecture:** The project is layered: pure Python search core, PostgreSQL storage, service orchestration, FastAPI API routes, Redis cache/broker, and Celery background workers. The search core must remain independent from FastAPI and the database so the algorithms are easy to test and explain.

**Tech Stack:** Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Redis, Celery, pytest, Docker Compose.

## Global Constraints

- Backend-only first; no frontend in the first backend version.
- Build from scratch; do not copy implementation code from `keshavpj1711/searchEng2.0`.
- Use the reference repo only to compare architecture, features, and learning goals.
- PostgreSQL is the source of truth for documents and job metadata.
- Redis is used for Celery broker/backend, query cache, index version cache, and index snapshots once stable.
- The active search index starts as an in-memory Python object.
- The search core uses a configurable analyzer pipeline.
- The simple analyzer is the baseline; the advanced analyzer adds stemming.
- BM25 is the default ranking algorithm.
- TF-IDF remains available for comparison and learning.
- Every technical task starts with explanation, then tests, then implementation, then verification, then commit.
- Do not implement a task until the user approves starting that task.
- Keep commits small and meaningful.

---

## Learning Workflow

Every task follows this rhythm:

1. Explain the concept in plain language.
2. Explain why this project needs it.
3. Write or inspect the failing test first when the task touches behavior.
4. Implement the smallest working version.
5. Run the exact verification command.
6. Explain the code line by line where useful.
7. Commit only that task.

The user and agent will build one task at a time. The agent should stop after each task's verification and ask before moving to the next task.

## Target File Structure

```text
.
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py
│   │       ├── health.py
│   │       ├── documents.py
│   │       ├── search.py
│   │       ├── jobs.py
│   │       └── crawl.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── models.py
│   │   └── session.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── documents.py
│   │   ├── jobs.py
│   │   ├── crawl_runs.py
│   │   └── index_versions.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── documents.py
│   │   ├── search.py
│   │   ├── jobs.py
│   │   └── crawl.py
│   ├── search/
│   │   ├── __init__.py
│   │   ├── types.py
│   │   ├── analyzer.py
│   │   ├── inverted_index.py
│   │   ├── tfidf.py
│   │   ├── bm25.py
│   │   └── engine.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── documents.py
│   │   ├── search.py
│   │   ├── indexing.py
│   │   ├── jobs.py
│   │   ├── cache.py
│   │   └── crawler.py
│   ├── workers/
│   │   ├── __init__.py
│   │   ├── celery_app.py
│   │   └── tasks.py
│   └── crawler/
│       ├── __init__.py
│       └── wikipedia.py
├── alembic/
│   ├── env.py
│   └── versions/
├── tests/
│   ├── unit/
│   │   └── search/
│   └── integration/
├── scripts/
│   └── benchmark_search.py
├── docs/
│   └── superpowers/
│       ├── specs/
│       └── plans/
├── .env.example
├── .gitignore
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## Interface Map

Core data types:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class IndexedDocument:
    id: int
    title: str
    content: str
    url: str | None = None

@dataclass(frozen=True)
class Posting:
    document_id: int
    term_frequency: int

@dataclass(frozen=True)
class SearchHit:
    document_id: int
    score: float
    matched_terms: list[str]
```

Core search interfaces:

```python
class BaseAnalyzer:
    def analyze(self, text: str) -> list[str]:
        raise NotImplementedError

class SimpleAnalyzer(BaseAnalyzer):
    def analyze(self, text: str) -> list[str]:
        raise NotImplementedError

class AdvancedAnalyzer(BaseAnalyzer):
    def analyze(self, text: str) -> list[str]:
        raise NotImplementedError

class InvertedIndex:
    def add_document(self, document: IndexedDocument) -> None:
        raise NotImplementedError

    def remove_document(self, document_id: int) -> None:
        raise NotImplementedError

    def get_postings(self, term: str) -> list[Posting]:
        raise NotImplementedError

    def document_count(self) -> int:
        raise NotImplementedError

class TfidfRanker:
    def score(self, query_terms: list[str], index: InvertedIndex) -> list[SearchHit]:
        raise NotImplementedError

class Bm25Ranker:
    def score(self, query_terms: list[str], index: InvertedIndex) -> list[SearchHit]:
        raise NotImplementedError

class SearchEngine:
    def index_document(self, document: IndexedDocument) -> None:
        raise NotImplementedError

    def remove_document(self, document_id: int) -> None:
        raise NotImplementedError

    def search(self, query: str, ranking: str, limit: int) -> list[SearchHit]:
        raise NotImplementedError

    def explain(self, query: str, document_id: int, ranking: str) -> dict:
        raise NotImplementedError
```

Service interfaces:

```python
class DocumentService:
    def create_document(self, payload: DocumentCreate) -> DocumentRead:
        raise NotImplementedError

    def update_document(self, document_id: int, payload: DocumentUpdate) -> DocumentRead:
        raise NotImplementedError

    def delete_document(self, document_id: int) -> None:
        raise NotImplementedError

class SearchService:
    def search(self, query: str, ranking: str, limit: int) -> SearchResponse:
        raise NotImplementedError

    def explain(self, query: str, document_id: int, ranking: str) -> SearchExplainResponse:
        raise NotImplementedError

class JobService:
    def create_job(self, job_type: str) -> JobRead:
        raise NotImplementedError

    def mark_running(self, job_id: str) -> None:
        raise NotImplementedError

    def mark_completed(self, job_id: str, result: dict) -> None:
        raise NotImplementedError

    def mark_failed(self, job_id: str, error: str) -> None:
        raise NotImplementedError
```

---

## Task 1: Project Scaffold And Health Endpoint

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `app/main.py`
- Create: `app/api/__init__.py`
- Create: `app/api/v1/__init__.py`
- Create: `app/api/v1/router.py`
- Create: `app/api/v1/health.py`
- Create: `tests/integration/test_health_api.py`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Modify: `README.md`

**Interfaces:**
- Produces: FastAPI app object named `app` in `app/main.py`.
- Produces: `GET /api/v1/health` returning `{"status": "ok", "service": "search-engine"}`.
- Produces: Docker Compose services named `api`, `postgres`, `redis`, and `celery_worker`.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
What FastAPI does
Why routers are separated from app/main.py
Why /api/v1 is better than unversioned routes
Why Docker Compose is useful before we even use every service
```

User must confirm these ideas before writing files.

- [ ] **Step 2: Write the failing health test**

Create `tests/integration/test_health_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok_status():
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "search-engine",
    }
```

- [ ] **Step 3: Run the failing test**

Run:

```bash
pytest tests/integration/test_health_api.py -v
```

Expected:

```text
FAIL because app.main or the /api/v1/health route does not exist yet
```

- [ ] **Step 4: Create the minimal FastAPI app and route**

Create `app/api/v1/health.py`:

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "search-engine",
    }
```

Create `app/api/v1/router.py`:

```python
from fastapi import APIRouter

from app.api.v1.health import router as health_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
```

Create `app/main.py`:

```python
from fastapi import FastAPI

from app.api.v1.router import api_router

app = FastAPI(
    title="Search Engine API",
    version="0.1.0",
)

app.include_router(api_router)
```

- [ ] **Step 5: Add initial dependencies**

Create `requirements.txt`:

```text
fastapi
uvicorn[standard]
pydantic
pydantic-settings
sqlalchemy
psycopg[binary]
alembic
redis
celery
aiohttp
beautifulsoup4
nltk
```

Create `requirements-dev.txt`:

```text
-r requirements.txt
pytest
pytest-asyncio
httpx
```

- [ ] **Step 6: Add local environment and Docker files**

Create `.env.example`:

```text
APP_NAME=search-engine
ENVIRONMENT=local
DATABASE_URL=postgresql+psycopg://search_user:search_password@postgres:5432/search_engine
REDIS_URL=redis://redis:6379/0
```

Create `.gitignore`:

```text
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
.env
.DS_Store
dist/
build/
*.egg-info/
```

Create `Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `docker-compose.yml`:

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env.example
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: search_engine
      POSTGRES_USER: search_user
      POSTGRES_PASSWORD: search_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  celery_worker:
    build: .
    env_file:
      - .env.example
    depends_on:
      - postgres
      - redis
    command: celery -A app.workers.celery_app worker --loglevel=info

volumes:
  postgres_data:
```

- [ ] **Step 7: Run verification**

Run:

```bash
pytest tests/integration/test_health_api.py -v
```

Expected:

```text
1 passed
```

Run:

```bash
docker compose config
```

Expected:

```text
Compose file renders without errors
```

- [ ] **Step 8: Commit**

```bash
git add .gitignore .env.example Dockerfile docker-compose.yml requirements.txt requirements-dev.txt app tests README.md
git commit -m "feat: scaffold FastAPI service"
```

---

## Task 2: Configuration, Database Session, And Migrations

**Files:**
- Create: `app/core/__init__.py`
- Create: `app/core/config.py`
- Create: `app/db/__init__.py`
- Create: `app/db/base.py`
- Create: `app/db/session.py`
- Create: `app/db/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_create_core_tables.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/integration/test_database_schema.py`

**Interfaces:**
- Consumes: environment variables from `.env.example`.
- Produces: `settings: Settings` in `app/core/config.py`.
- Produces: `SessionLocal` and `get_db_session()` in `app/db/session.py`.
- Produces: SQLAlchemy models `Document`, `Job`, `CrawlRun`, `IndexVersion`.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
Why PostgreSQL is the source of truth
What SQLAlchemy ORM means
What Alembic migrations solve
Why app code should not open raw database connections everywhere
```

- [ ] **Step 2: Write config test**

Create `tests/unit/test_config.py`:

```python
from app.core.config import Settings


def test_settings_reads_database_and_redis_urls():
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.database_url == "postgresql+psycopg://u:p@localhost:5432/db"
    assert settings.redis_url == "redis://localhost:6379/0"
```

- [ ] **Step 3: Implement settings**

Create `app/core/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "search-engine"
    environment: str = "local"
    database_url: str
    redis_url: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
```

- [ ] **Step 4: Define SQLAlchemy models**

Create `app/db/base.py`, `app/db/session.py`, and `app/db/models.py` with:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

```python
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000), unique=True, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class IndexVersion(Base):
    __tablename__ = "index_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unique_term_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 5: Add migration**

Create Alembic config and migration so these tables are created exactly once. The migration must include:

```text
documents
jobs
crawl_runs
index_versions
unique constraint on documents.url
unique constraint on index_versions.version
```

- [ ] **Step 6: Run verification**

Run:

```bash
pytest tests/unit/test_config.py -v
docker compose up -d postgres
alembic upgrade head
pytest tests/integration/test_database_schema.py -v
```

Expected:

```text
Config test passes
PostgreSQL starts
Alembic applies migration
Schema integration test passes
```

- [ ] **Step 7: Commit**

```bash
git add app/core app/db alembic alembic.ini tests
git commit -m "feat: add database schema and migrations"
```

---

## Task 3: Document Schemas, Repository, And CRUD API

**Files:**
- Create: `app/schemas/__init__.py`
- Create: `app/schemas/documents.py`
- Create: `app/repositories/__init__.py`
- Create: `app/repositories/documents.py`
- Create: `app/services/__init__.py`
- Create: `app/services/documents.py`
- Create: `app/api/v1/documents.py`
- Modify: `app/api/v1/router.py`
- Create: `tests/integration/test_documents_api.py`

**Interfaces:**
- Consumes: `Document` SQLAlchemy model.
- Produces: `DocumentCreate`, `DocumentUpdate`, `DocumentRead`.
- Produces: `DocumentRepository`.
- Produces: `POST`, `GET`, `PUT`, and `DELETE` document endpoints.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
What Pydantic schemas do
Why repository code is separate from API route code
Why duplicate URLs should return 409 Conflict
Why delete should mark or remove documents consistently
```

- [ ] **Step 2: Write API lifecycle tests**

Create tests for:

```text
POST /api/v1/documents creates a document
GET /api/v1/documents/{id} returns it
PUT /api/v1/documents/{id} updates it
DELETE /api/v1/documents/{id} removes it from normal reads
POST duplicate URL returns 409
```

Use this request body:

```json
{
  "title": "Machine Learning Basics",
  "url": "https://example.com/ml-basics",
  "content": "Machine learning is a field of artificial intelligence."
}
```

- [ ] **Step 3: Implement schemas**

Create `app/schemas/documents.py`:

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl | None = None
    content: str = Field(min_length=1)


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    url: HttpUrl | None = None
    content: str | None = Field(default=None, min_length=1)


class DocumentRead(BaseModel):
    id: int
    title: str
    url: str | None
    content: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: Implement repository and service**

Repository methods:

```python
class DocumentRepository:
    def create(self, payload: DocumentCreate) -> Document:
        raise NotImplementedError

    def get_active(self, document_id: int) -> Document | None:
        raise NotImplementedError

    def update(self, document_id: int, payload: DocumentUpdate) -> Document | None:
        raise NotImplementedError

    def soft_delete(self, document_id: int) -> bool:
        raise NotImplementedError

    def list_active(self) -> list[Document]:
        raise NotImplementedError
```

Service behavior:

```text
create: save document and return DocumentRead
get: 404 when active document missing
update: 404 when active document missing
delete: 204 when active document exists, 404 otherwise
duplicate URL: 409 Conflict
```

- [ ] **Step 5: Add routes**

Routes:

```text
POST   /api/v1/documents
GET    /api/v1/documents/{document_id}
PUT    /api/v1/documents/{document_id}
DELETE /api/v1/documents/{document_id}
```

- [ ] **Step 6: Run verification**

Run:

```bash
pytest tests/integration/test_documents_api.py -v
```

Expected:

```text
All document lifecycle tests pass
```

- [ ] **Step 7: Commit**

```bash
git add app/schemas app/repositories app/services app/api/v1 tests/integration/test_documents_api.py
git commit -m "feat: add document CRUD API"
```

---

## Task 4: Analyzer Pipeline

**Files:**
- Create: `app/search/__init__.py`
- Create: `app/search/analyzer.py`
- Create: `tests/unit/search/test_analyzer.py`

**Interfaces:**
- Produces: `BaseAnalyzer.analyze(text: str) -> list[str]`.
- Produces: `SimpleAnalyzer.analyze(text: str) -> list[str]`.
- Produces: `AdvancedAnalyzer.analyze(text: str) -> list[str]`.
- Produces: simple normalization, stopword removal, and stemming for indexing and query processing.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
What tokenization means
Why search compares normalized terms instead of raw text
Why stopwords reduce noise
What we lose when we remove punctuation and lowercase text
What stemming does
Why stemming can improve recall but reduce precision
Why analyzers should be configurable instead of hardcoded
```

- [ ] **Step 2: Write analyzer tests**

Create `tests/unit/search/test_analyzer.py`:

```python
from app.search.analyzer import AdvancedAnalyzer, SimpleAnalyzer


def test_simple_analyzer_lowercases_and_removes_punctuation():
    analyzer = SimpleAnalyzer()

    terms = analyzer.analyze("Machine-Learning, Basics!")

    assert terms == ["machine", "learning", "basics"]


def test_simple_analyzer_removes_stopwords():
    analyzer = SimpleAnalyzer(stopwords={"is", "a", "of"})

    terms = analyzer.analyze("Machine learning is a field of AI")

    assert terms == ["machine", "learning", "field", "ai"]


def test_simple_analyzer_returns_empty_list_for_blank_text():
    analyzer = SimpleAnalyzer()

    assert analyzer.analyze("   ") == []


def test_advanced_analyzer_stems_related_words():
    analyzer = AdvancedAnalyzer(stopwords=set())

    terms = analyzer.analyze("running runs runner")

    assert terms == ["run", "run", "runner"]


def test_simple_and_advanced_analyzers_can_behave_differently():
    simple = SimpleAnalyzer(stopwords=set())
    advanced = AdvancedAnalyzer(stopwords=set())

    assert simple.analyze("running") == ["running"]
    assert advanced.analyze("running") == ["run"]
```

- [ ] **Step 3: Implement analyzer pipeline**

Create `app/search/analyzer.py`:

```python
import re

from nltk.stem import PorterStemmer

DEFAULT_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}


class BaseAnalyzer:
    def analyze(self, text: str) -> list[str]:
        raise NotImplementedError


class SimpleAnalyzer(BaseAnalyzer):
    def __init__(self, stopwords: set[str] | None = None) -> None:
        self.stopwords = stopwords if stopwords is not None else DEFAULT_STOPWORDS

    def analyze(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []

        normalized = text.lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        terms = normalized.split()
        return [term for term in terms if term not in self.stopwords]


class AdvancedAnalyzer(SimpleAnalyzer):
    def __init__(self, stopwords: set[str] | None = None) -> None:
        super().__init__(stopwords=stopwords)
        self.stemmer = PorterStemmer()

    def analyze(self, text: str) -> list[str]:
        terms = super().analyze(text)
        return [self.stemmer.stem(term) for term in terms]
```

- [ ] **Step 4: Run verification**

Run:

```bash
pytest tests/unit/search/test_analyzer.py -v
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add app/search tests/unit/search/test_analyzer.py
git commit -m "feat: add analyzer pipeline"
```

---

## Task 5: Inverted Index

**Files:**
- Create: `app/search/types.py`
- Create: `app/search/inverted_index.py`
- Create: `tests/unit/search/test_inverted_index.py`

**Interfaces:**
- Consumes: `BaseAnalyzer`.
- Produces: `IndexedDocument`, `Posting`, and `InvertedIndex`.
- Produces term postings, document lengths, average document length, and document term frequencies used by TF-IDF and BM25.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
Why inverted index is not an alternative to BM25
Why the index stores term -> documents
Why term frequency and document length are needed for ranking
How this avoids scanning every document for every query
```

- [ ] **Step 2: Write inverted index tests**

Create tests for:

```text
term postings include matching document ids
term frequency is counted
document length is stored
average document length is computed
removing a document removes its postings
```

Use documents:

```python
IndexedDocument(id=1, title="Python Search", content="python search search")
IndexedDocument(id=2, title="Java Search", content="java search engine")
```

- [ ] **Step 3: Implement core types**

Create `app/search/types.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexedDocument:
    id: int
    title: str
    content: str
    url: str | None = None


@dataclass(frozen=True)
class Posting:
    document_id: int
    term_frequency: int


@dataclass(frozen=True)
class SearchHit:
    document_id: int
    score: float
    matched_terms: list[str]
```

- [ ] **Step 4: Implement inverted index**

Create `app/search/inverted_index.py` with:

```python
class InvertedIndex:
    def __init__(self, analyzer: BaseAnalyzer) -> None:
        raise NotImplementedError

    def add_document(self, document: IndexedDocument) -> None:
        raise NotImplementedError

    def remove_document(self, document_id: int) -> None:
        raise NotImplementedError

    def get_postings(self, term: str) -> list[Posting]:
        raise NotImplementedError

    def document_frequency(self, term: str) -> int:
        raise NotImplementedError

    def term_frequency(self, document_id: int, term: str) -> int:
        raise NotImplementedError

    def document_length(self, document_id: int) -> int:
        raise NotImplementedError

    def average_document_length(self) -> float:
        raise NotImplementedError

    def document_count(self) -> int:
        raise NotImplementedError

    def unique_term_count(self) -> int:
        raise NotImplementedError
```

Implementation rule:

```text
Combine title and content for indexing, with title included twice to give title matches extra weight.
```

- [ ] **Step 5: Run verification**

Run:

```bash
pytest tests/unit/search/test_inverted_index.py -v
```

Expected:

```text
All inverted index tests pass
```

- [ ] **Step 6: Commit**

```bash
git add app/search tests/unit/search/test_inverted_index.py
git commit -m "feat: add inverted index"
```

---

## Task 6: TF-IDF Ranker

**Files:**
- Create: `app/search/tfidf.py`
- Create: `tests/unit/search/test_tfidf.py`

**Interfaces:**
- Consumes: `InvertedIndex`.
- Produces: `TfidfRanker.score(query_terms, index, limit) -> list[SearchHit]`.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
TF means how important a term is inside one document
IDF means how rare a term is across all documents
Common words should have lower score
Rare query terms should influence ranking more
```

- [ ] **Step 2: Write TF-IDF tests**

Tests:

```text
document with higher query term frequency ranks higher
term appearing in every document has lower IDF than rare term
empty query terms return no hits
```

- [ ] **Step 3: Implement TF-IDF**

Formula:

```python
tf = term_frequency / document_length
idf = math.log((1 + document_count) / (1 + document_frequency)) + 1
score = sum(tf * idf for each query term)
```

Class:

```python
class TfidfRanker:
    def score(
        self,
        query_terms: list[str],
        index: InvertedIndex,
        limit: int = 10,
    ) -> list[SearchHit]:
        raise NotImplementedError
```

- [ ] **Step 4: Run verification**

Run:

```bash
pytest tests/unit/search/test_tfidf.py -v
```

Expected:

```text
All TF-IDF tests pass
```

- [ ] **Step 5: Commit**

```bash
git add app/search/tfidf.py tests/unit/search/test_tfidf.py
git commit -m "feat: add tf-idf ranker"
```

---

## Task 7: BM25 Ranker

**Files:**
- Create: `app/search/bm25.py`
- Create: `tests/unit/search/test_bm25.py`

**Interfaces:**
- Consumes: `InvertedIndex`.
- Produces: `Bm25Ranker.score(query_terms, index, limit) -> list[SearchHit]`.
- Produces: `Bm25Ranker.explain(query_terms, document_id, index) -> dict`.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
Why TF-IDF can over-reward repeated words
Why long documents need normalization
What k1 controls in BM25
What b controls in BM25
Why BM25 is stronger for this project
```

- [ ] **Step 2: Write BM25 tests**

Tests:

```text
exact matching document ranks above unrelated document
term repetition saturates instead of growing linearly
long document is not automatically rewarded over focused document
explanation returns per-term score contribution
```

- [ ] **Step 3: Implement BM25**

Formula:

```python
idf = math.log(1 + ((document_count - document_frequency + 0.5) / (document_frequency + 0.5)))
numerator = term_frequency * (k1 + 1)
denominator = term_frequency + k1 * (1 - b + b * document_length / average_document_length)
score = idf * numerator / denominator
```

Defaults:

```python
k1 = 1.5
b = 0.75
```

- [ ] **Step 4: Run verification**

Run:

```bash
pytest tests/unit/search/test_bm25.py -v
```

Expected:

```text
All BM25 tests pass
```

- [ ] **Step 5: Commit**

```bash
git add app/search/bm25.py tests/unit/search/test_bm25.py
git commit -m "feat: add bm25 ranker"
```

---

## Task 8: Search Engine Wrapper And Search API

**Files:**
- Create: `app/search/engine.py`
- Create: `app/schemas/search.py`
- Create: `app/services/search.py`
- Create: `app/services/indexing.py`
- Create: `app/api/v1/search.py`
- Modify: `app/api/v1/router.py`
- Create: `tests/unit/search/test_engine.py`
- Create: `tests/integration/test_search_api.py`

**Interfaces:**
- Consumes: `BaseAnalyzer`, `InvertedIndex`, `TfidfRanker`, `Bm25Ranker`.
- Produces: `/api/v1/search`.
- Produces: `/api/v1/search/explain`.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
Why SearchEngine coordinates smaller classes
Why BM25 should be default
Why unsupported ranking values should return a validation error
Why explanation endpoint is strong for interviews
```

- [ ] **Step 2: Write engine and API tests**

Tests:

```text
search defaults to BM25
ranking=tfidf uses TF-IDF
empty query returns 422 or clear validation response
search returns score, title, snippet, matched terms
explain returns final_score and term contributions
```

- [ ] **Step 3: Implement schemas**

Search request query parameters:

```text
q: str
ranking: "bm25" or "tfidf"
limit: int from 1 to 50
```

Response models:

```python
class SearchResult(BaseModel):
    document_id: int
    title: str
    url: str | None
    score: float
    snippet: str
    matched_terms: list[str]


class SearchResponse(BaseModel):
    query: str
    ranking: str
    total_results: int
    index_version: str
    results: list[SearchResult]
```

- [ ] **Step 4: Implement search behavior**

Rules:

```text
Index active documents from PostgreSQL at app startup.
Use in-memory index for query candidate lookup.
Fetch result metadata from PostgreSQL after ranking.
Snippet is the first content segment containing any matched term; if none, use first 180 characters.
```

- [ ] **Step 5: Run verification**

Run:

```bash
pytest tests/unit/search/test_engine.py tests/integration/test_search_api.py -v
```

Expected:

```text
All search engine and API tests pass
```

- [ ] **Step 6: Commit**

```bash
git add app/search app/schemas/search.py app/services/search.py app/services/indexing.py app/api/v1/search.py app/api/v1/router.py tests
git commit -m "feat: add search API"
```

---

## Task 9: Redis Cache And Index Versioning

**Files:**
- Create: `app/services/cache.py`
- Create: `app/repositories/index_versions.py`
- Create: `tests/unit/test_cache_keys.py`
- Create: `tests/integration/test_search_cache.py`

**Interfaces:**
- Consumes: `REDIS_URL`.
- Produces: cache keys using current index version.
- Produces: index version records in PostgreSQL.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
Why repeated queries should be cached
Why cached search results become wrong after index changes
How index versioning solves cache invalidation
Why Redis is cache, not source of truth
```

- [ ] **Step 2: Write cache key tests**

Expected key shape:

```text
search:v{index_version}:ranking:{ranking}:limit:{limit}:q:{normalized_query_hash}
```

- [ ] **Step 3: Implement cache service**

Methods:

```python
class CacheService:
    def get_json(self, key: str) -> dict | None:
        raise NotImplementedError

    def set_json(self, key: str, value: dict, ttl_seconds: int) -> None:
        raise NotImplementedError

    def search_cache_key(self, query: str, ranking: str, limit: int, index_version: str) -> str:
        raise NotImplementedError
```

- [ ] **Step 4: Connect cache to search service**

Rules:

```text
Check Redis before executing search.
Write successful search response to Redis.
Use 300 second TTL for search responses.
Include index_version in every search response.
```

- [ ] **Step 5: Run verification**

Run:

```bash
pytest tests/unit/test_cache_keys.py tests/integration/test_search_cache.py -v
```

Expected:

```text
Cache keys are stable
Repeated search can be served from Redis
Changing index version changes the cache key
```

- [ ] **Step 6: Commit**

```bash
git add app/services/cache.py app/repositories/index_versions.py tests
git commit -m "feat: add search cache versioning"
```

---

## Task 10: Celery Worker And Job Tracking

**Files:**
- Create: `app/schemas/jobs.py`
- Create: `app/repositories/jobs.py`
- Create: `app/services/jobs.py`
- Create: `app/workers/__init__.py`
- Create: `app/workers/celery_app.py`
- Create: `app/workers/tasks.py`
- Create: `app/api/v1/jobs.py`
- Modify: `app/api/v1/router.py`
- Modify: `app/services/documents.py`
- Create: `tests/integration/test_jobs_api.py`
- Create: `tests/unit/test_job_service.py`

**Interfaces:**
- Produces: Celery app named `celery_app`.
- Produces: `GET /api/v1/jobs/{job_id}`.
- Produces job statuses: `pending`, `running`, `completed`, `failed`.
- Produces Celery task `index_document(document_id: int, job_id: str)`.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
Why API requests should not wait for expensive indexing
What eventual consistency means
Why a job status endpoint matters
How Redis is used as Celery broker/backend
```

- [ ] **Step 2: Write job tests**

Tests:

```text
creating document returns a job id
GET /api/v1/jobs/{job_id} returns pending/running/completed/failed
missing job returns 404
job service can mark running, completed, and failed
```

- [ ] **Step 3: Implement Celery app**

Create `app/workers/celery_app.py`:

```python
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "search_engine",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
```

- [ ] **Step 4: Implement job service**

Methods:

```python
class JobService:
    def create_job(self, job_type: str, total_items: int = 0) -> JobRead:
        raise NotImplementedError

    def get_job(self, job_id: str) -> JobRead:
        raise NotImplementedError

    def mark_running(self, job_id: str) -> None:
        raise NotImplementedError

    def mark_completed(self, job_id: str, result: dict) -> None:
        raise NotImplementedError

    def mark_failed(self, job_id: str, error: str) -> None:
        raise NotImplementedError
```

- [ ] **Step 5: Wire document creation to indexing job**

Flow:

```text
POST /api/v1/documents
-> save document
-> create index_document job
-> queue Celery task
-> return document plus job_id
```

- [ ] **Step 6: Run verification**

Run:

```bash
pytest tests/unit/test_job_service.py tests/integration/test_jobs_api.py -v
docker compose config
```

Expected:

```text
Job service tests pass
Job API tests pass
Compose references app.workers.celery_app successfully
```

- [ ] **Step 7: Commit**

```bash
git add app/schemas/jobs.py app/repositories/jobs.py app/services/jobs.py app/workers app/api/v1/jobs.py app/api/v1/router.py app/services/documents.py tests
git commit -m "feat: add celery job tracking"
```

---

## Task 11: Bulk Document Ingestion

**Files:**
- Modify: `app/schemas/documents.py`
- Modify: `app/services/documents.py`
- Modify: `app/workers/tasks.py`
- Modify: `app/api/v1/documents.py`
- Create: `tests/integration/test_bulk_documents_api.py`

**Interfaces:**
- Produces: `POST /api/v1/documents/bulk`.
- Produces Celery task `bulk_ingest_documents(documents: list[dict], job_id: str)`.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
Why bulk ingestion should be background work
How duplicate URLs should be skipped or reported
Why validation errors should be visible in job result
When full index rebuild is simpler than incremental updates
```

- [ ] **Step 2: Write bulk ingestion tests**

Tests:

```text
bulk endpoint returns 202 Accepted and job id
job result includes inserted_count, skipped_count, failed_count
duplicate URL is counted as skipped
invalid empty content is counted as failed
```

- [ ] **Step 3: Implement bulk endpoint**

Request:

```json
{
  "documents": [
    {
      "title": "Python",
      "url": "https://example.com/python",
      "content": "Python is a programming language."
    }
  ]
}
```

Response:

```json
{
  "job_id": "uuid",
  "status": "pending",
  "total_items": 1
}
```

- [ ] **Step 4: Implement bulk Celery task**

Rules:

```text
Validate every document.
Insert valid new documents.
Skip duplicate URLs.
Record failed documents with reason.
Trigger index rebuild after ingestion completes.
Mark job completed with counts.
```

- [ ] **Step 5: Run verification**

Run:

```bash
pytest tests/integration/test_bulk_documents_api.py -v
```

Expected:

```text
Bulk ingestion API tests pass
```

- [ ] **Step 6: Commit**

```bash
git add app/schemas/documents.py app/services/documents.py app/workers/tasks.py app/api/v1/documents.py tests/integration/test_bulk_documents_api.py
git commit -m "feat: add bulk document ingestion"
```

---

## Task 12: Wikipedia Crawler

**Files:**
- Create: `app/schemas/crawl.py`
- Create: `app/repositories/crawl_runs.py`
- Create: `app/services/crawler.py`
- Create: `app/crawler/__init__.py`
- Create: `app/crawler/wikipedia.py`
- Create: `app/api/v1/crawl.py`
- Modify: `app/api/v1/router.py`
- Modify: `app/workers/tasks.py`
- Create: `tests/unit/test_wikipedia_crawler.py`
- Create: `tests/integration/test_crawl_api.py`

**Interfaces:**
- Produces: `POST /api/v1/crawl/wikipedia`.
- Produces Celery task `crawl_wikipedia(limit: int, job_id: str)`.
- Produces crawl result counts: fetched, skipped, failed.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
Why crawler belongs in background worker
Why rate limiting is necessary
Why retries should use exponential backoff
Why tests should mock Wikipedia HTTP responses
What robots.txt and respectful scraping mean
```

- [ ] **Step 2: Write crawler unit tests**

Tests:

```text
featured article list parser extracts title and URL
article content parser extracts paragraph text
empty article content is marked failed
duplicate article URL is counted as skipped during persistence
```

- [ ] **Step 3: Implement Wikipedia crawler**

Crawler settings:

```text
source URL: https://en.wikipedia.org/wiki/Wikipedia:Featured_articles
concurrency limit: 5
request timeout: 30 seconds
max retries: 3
backoff seconds: 2, 4, 8
default User-Agent: search-engine-learning-project/0.1
```

Crawler functions:

```python
async def fetch_featured_article_links(limit: int) -> list[WikipediaArticleLink]:
    raise NotImplementedError


async def fetch_article_content(link: WikipediaArticleLink) -> CrawledDocument:
    raise NotImplementedError


async def crawl_featured_articles(limit: int) -> list[CrawledDocument]:
    raise NotImplementedError
```

- [ ] **Step 4: Add crawl API**

Request:

```json
{
  "limit": 100
}
```

Response:

```json
{
  "job_id": "uuid",
  "status": "pending",
  "source": "wikipedia_featured_articles",
  "requested_limit": 100
}
```

- [ ] **Step 5: Run verification**

Run:

```bash
pytest tests/unit/test_wikipedia_crawler.py tests/integration/test_crawl_api.py -v
```

Expected:

```text
Crawler parser tests pass with mocked HTML
Crawl API queues a job and records crawl run
```

- [ ] **Step 6: Commit**

```bash
git add app/schemas/crawl.py app/repositories/crawl_runs.py app/services/crawler.py app/crawler app/api/v1/crawl.py app/api/v1/router.py app/workers/tasks.py tests
git commit -m "feat: add wikipedia crawler ingestion"
```

---

## Task 13: Benchmarks

**Files:**
- Create: `scripts/benchmark_search.py`
- Create: `tests/unit/test_benchmark_dataset.py`
- Modify: `README.md`

**Interfaces:**
- Produces command: `python scripts/benchmark_search.py --documents 1000 --queries 50`.
- Produces metrics: document count, unique terms, build time, average latency, p95 latency, ranking algorithm comparison.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
Why benchmark claims need evidence
What average latency means
What p95 latency means
Why BM25 and TF-IDF should be compared on the same corpus
Why benchmark data should not be exaggerated
```

- [ ] **Step 2: Write benchmark data test**

Test:

```text
synthetic benchmark document generator creates deterministic documents
same seed produces same documents
different topics produce searchable terms
```

- [ ] **Step 3: Implement benchmark script**

Command:

```bash
python scripts/benchmark_search.py --documents 1000 --queries 50
```

Output shape:

```text
Documents indexed: 1000
Unique terms: prints an integer greater than or equal to 1 when at least one generated document contains searchable text
Index build time: prints seconds with three decimal places
BM25 avg latency: prints milliseconds with three decimal places
BM25 p95 latency: prints milliseconds with three decimal places
TF-IDF avg latency: prints milliseconds with three decimal places
TF-IDF p95 latency: prints milliseconds with three decimal places
```

- [ ] **Step 4: Run verification**

Run:

```bash
pytest tests/unit/test_benchmark_dataset.py -v
python scripts/benchmark_search.py --documents 100 --queries 10
```

Expected:

```text
Benchmark test passes
Benchmark script prints metrics without crashing
```

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark_search.py tests/unit/test_benchmark_dataset.py README.md
git commit -m "feat: add search benchmarks"
```

---

## Task 14: Documentation And Interview Story

**Files:**
- Modify: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/interview-notes.md`
- Create: `docs/api-examples.md`

**Interfaces:**
- Produces: README quickstart.
- Produces: architecture explanation.
- Produces: interview notes for TF-IDF, BM25, inverted index, Redis, Celery, PostgreSQL, and scaling.

- [ ] **Step 1: Learning checkpoint**

Explain:

```text
How to present this project in a placement interview
How to answer why PostgreSQL instead of SQLite
How to answer why BM25 instead of only TF-IDF
How to answer what breaks at larger scale
```

- [ ] **Step 2: Write README sections**

README must include:

```text
Project summary
Architecture diagram
Tech stack
Quickstart
API examples
Search algorithm explanation
Benchmark results
Comparison with reference project
Future improvements
```

- [ ] **Step 3: Write architecture docs**

`docs/architecture.md` must explain:

```text
Layered architecture
Data flow for document ingestion
Data flow for search
Data flow for Wikipedia crawling
Cache invalidation through index versions
Eventual consistency from Celery jobs
```

- [ ] **Step 4: Write interview notes**

`docs/interview-notes.md` must include short answers to:

```text
What is an inverted index?
How does TF-IDF work?
How does BM25 improve on TF-IDF?
Why did you use PostgreSQL?
Why did you use Redis?
Why did you use Celery?
How would you scale this?
What would you change for millions of documents?
```

- [ ] **Step 5: Run verification**

Run:

```bash
pytest -v
docker compose config
```

Expected:

```text
All tests pass
Compose file is valid
Docs match implemented endpoints and commands
```

- [ ] **Step 6: Commit**

```bash
git add README.md docs
git commit -m "docs: add project explanation and interview notes"
```

---

## Final Completion Checklist

- [ ] `pytest -v` passes.
- [ ] `docker compose up --build` starts API, PostgreSQL, Redis, and Celery worker.
- [ ] `GET /api/v1/health` returns status `ok`.
- [ ] Document CRUD works.
- [ ] Search works with `ranking=bm25`.
- [ ] Search works with `ranking=tfidf`.
- [ ] Search explanation returns per-term contributions.
- [ ] Jobs API returns job status.
- [ ] Bulk ingestion queues and completes a job.
- [ ] Wikipedia crawler queues and completes a job with mocked tests and real manual demo.
- [ ] Benchmark script prints metrics.
- [ ] README contains quickstart, examples, architecture, benchmarks, and interview story.
- [ ] Final project is pushed to `satyamarora26/search-engine`.

## Execution Rule

Do not start Task 1 until the user approves this plan. During execution, stop after every task, explain what changed, show test evidence, commit, push, and ask before starting the next task.
