# Wikipedia Category Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a bounded, policy-compliant, durable English Wikipedia category crawler whose successfully extracted articles enter PostgreSQL and one atomically published BM25 snapshot.

**Architecture:** FastAPI stores a crawl job, request, and root frontier in PostgreSQL before sending only the shared UUID to Celery. The worker resumes an Action API breadth-first frontier, fetches Core REST HTML through one rate-limited asynchronous client, stages normalized document payloads through the existing ingestion boundary, and publishes one Redis search snapshot after all page outcomes are terminal.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.x, PostgreSQL 16, Alembic, Celery, Redis 7, HTTPX, BeautifulSoup4, lxml, pytest

**Design:** `docs/superpowers/specs/2026-07-21-wikipedia-category-crawler-design.md`

## Global Constraints

- Crawl only English Wikipedia; source hosts and API paths come from trusted server configuration, never request URLs.
- Use `Category:Featured articles`, 100 articles, and depth zero as request defaults.
- Accept 1 to 500 articles and subcategory depth zero through two.
- Visit no more than 100 categories per run and record whether another eligible category was suppressed.
- Discover namespace-zero articles and namespace-fourteen subcategories through `list=categorymembers` in deterministic ascending order.
- Fetch full article content from the MediaWiki Core REST HTML endpoint.
- Permit at most four concurrent Wikimedia requests and two request starts per second across discovery and fetching.
- Use a 30-second request timeout, a 10 MiB streamed-response limit, and at most three HTTP attempts.
- Honor valid `Retry-After` values and use exponential backoff with full jitter for retryable failures.
- Send `SatyamSearchEngineBot/1.0 (https://github.com/satyamarora26/search-engine)` unless a nonblank configured value replaces it.
- Never hold a database session or transaction during an HTTP wait.
- Never store raw HTML or expose article content through crawler item reports or logs.
- Preserve Unicode prose; reject extracted content shorter than 100 visible characters.
- Use one UUID for the public job id, PostgreSQL job id, and Celery task id.
- Use `job_type="wikipedia_crawl"` and `resource_key="search_index"` for the entire run.
- Reuse `IngestionItemProcessor`; do not duplicate document validation or duplicate-URL behavior.
- Rebuild BM25 once only when at least one document imports; duplicate-only runs retain the active version.
- Allow partial success only when at least one page imports or is safely skipped as a duplicate.
- Keep raw exception details in logs and durable/public errors stable and sanitized.
- Preserve existing document, bulk ingestion, rebuild, search, and snapshot contracts.
- Use `/opt/anaconda3/bin/python3 -m pytest` for this workspace's test environment.
- Commit and push every completed task directly to `main` after its focused tests pass.

## File Map

Create:

- `app/schemas/wikipedia_crawls.py`: strict crawl request and item-report contracts.
- `app/models/wikipedia_crawl.py`: crawl run, frontier, and discovered-page models.
- `app/services/wikipedia_types.py`: immutable source and phase DTOs shared without layer cycles.
- `app/repositories/wikipedia_crawls.py`: crawl CRUD, guarded transitions, counts, and report queries.
- `app/services/wikipedia_crawls.py`: API-facing transactional create/enqueue/report service.
- `app/api/v1/crawls.py`: Wikipedia crawl submission and item-report routes.
- `app/services/wikipedia_extraction.py`: pure Parsoid HTML-to-text extraction.
- `app/services/wikipedia_client.py`: rate-limited Action/Core REST client and HTTP error classification.
- `app/services/wikipedia_crawl_store.py`: short-session transactional crawl checkpoints.
- `app/services/wikipedia_discovery.py`: resumable breadth-first discovery phase.
- `app/services/wikipedia_fetching.py`: bounded asynchronous fetch, extract, and staging phase.
- `app/services/wikipedia_crawl_runner.py`: job lifecycle, ingestion, result, and index publication orchestration.
- `app/workers/wikipedia_tasks.py`: bound crash-safe Celery crawl task.
- `alembic/versions/20260721_0005_create_wikipedia_crawler.py`: crawler schema migration.
- `tests/fixtures/wikipedia/article.html`: representative Parsoid extraction fixture.
- `tests/support/__init__.py`: test-support package marker.
- `tests/support/fake_wikimedia.py`: deterministic local Action/Core REST server.
- `tests/unit/test_wikipedia_crawl_schemas.py`: request and report schema tests.
- `tests/unit/test_wikipedia_crawl_models.py`: model and PostgreSQL DDL tests.
- `tests/unit/test_wikipedia_crawl_repository.py`: query, transition, count, and report tests.
- `tests/unit/test_wikipedia_crawls.py`: API service transaction and enqueue tests.
- `tests/unit/test_wikipedia_extraction.py`: extraction and rejection tests.
- `tests/unit/test_wikipedia_client.py`: rate, retry, redirect, pagination, and size tests.
- `tests/unit/test_wikipedia_discovery.py`: bounded BFS and checkpoint-resume tests.
- `tests/unit/test_wikipedia_fetching.py`: batch fetch, extraction, staging, and page-failure tests.
- `tests/unit/test_wikipedia_crawl_runner.py`: lifecycle, progress, completion, and publication tests.
- `tests/unit/test_worker_wikipedia_tasks.py`: Celery lock, retry, routing, and redelivery tests.
- `tests/integration/test_wikipedia_crawl_api.py`: FastAPI request and item-report contracts.
- `tests/integration/test_wikipedia_crawl_postgres.py`: live schema, checkpoint, transition, and conflict tests.
- `tests/integration/test_wikipedia_crawl_e2e.py`: fake-Wikimedia to BM25 live-services flow.
- `docs/wikipedia-crawler.md`: local operation, outcomes, policy, and verification guide.

Modify:

- `requirements.txt`: replace `httpx2` with `httpx`; add `beautifulsoup4` and `lxml`.
- `.env.example`: document crawler configuration.
- `app/core/config.py`: typed crawler defaults and environment overrides.
- `app/models/job.py`: add the crawler job-type constant.
- `app/models/__init__.py`: export crawler models.
- `alembic/env.py`: register crawler models with Alembic metadata.
- `app/repositories/ingestion_items.py`: stage one payload at an explicit discovery position.
- `app/api/dependencies.py`: construct the crawl service with a named Celery signature.
- `app/api/v1/router.py`: register the crawl router.
- `app/workers/celery_app.py`: import the crawler task module.
- Existing configuration, Celery, and PostgreSQL tests: extend without weakening current assertions.

---

### Task 1: Define Crawl Request And Item-Report Contracts

**Files:**
- Create: `app/schemas/wikipedia_crawls.py`
- Create: `tests/unit/test_wikipedia_crawl_schemas.py`

**Interfaces:**
- Produces: `normalize_wikipedia_category(value: str) -> str`.
- Produces: `WikipediaCrawlRequest`, `WikipediaCrawlItemResponse`, and `WikipediaCrawlItemListResponse`.
- Consumes: Pydantic v2 and no database or HTTP component.

- [x] **Step 1: Write failing request-normalization tests**

Create `tests/unit/test_wikipedia_crawl_schemas.py` with these contracts:

```python
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.wikipedia_crawls import (
    WikipediaCrawlItemListResponse,
    WikipediaCrawlRequest,
)

JOB_ID = UUID("0ea30c3d-273f-44cc-a43f-489c2ece940d")


def test_request_uses_canonical_bounded_defaults():
    request = WikipediaCrawlRequest()

    assert request.category == "Category:Featured articles"
    assert request.max_articles == 100
    assert request.max_depth == 0


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("Physics", "Category:Physics"),
        (" Category:Physics ", "Category:Physics"),
        ("category:Featured articles", "Category:Featured articles"),
    ],
)
def test_request_canonicalizes_category_names(raw, canonical):
    assert WikipediaCrawlRequest(category=raw).category == canonical


@pytest.mark.parametrize(
    "category",
    [
        "",
        "   ",
        "Category:   ",
        "https://en.wikipedia.org/wiki/Physics",
        "Physics\x00",
        "x" * 255,
    ],
)
def test_request_rejects_blank_url_and_control_character_categories(category):
    with pytest.raises(ValidationError):
        WikipediaCrawlRequest(category=category)


@pytest.mark.parametrize(
    "payload",
    [
        {"max_articles": 0},
        {"max_articles": 501},
        {"max_articles": True},
        {"max_depth": -1},
        {"max_depth": 3},
        {"max_depth": False},
        {"language": "fr"},
    ],
)
def test_request_rejects_out_of_scope_values_and_unknown_fields(payload):
    with pytest.raises(ValidationError):
        WikipediaCrawlRequest.model_validate(payload)


def test_item_report_contains_outcomes_without_content_or_html():
    response = WikipediaCrawlItemListResponse.model_validate({
        "job_id": JOB_ID,
        "total_results": 1,
        "limit": 100,
        "offset": 0,
        "items": [{
            "position": 0,
            "wikipedia_page_id": 42,
            "title": "Information retrieval",
            "url": "https://en.wikipedia.org/wiki/Information_retrieval",
            "fetch_status": "fetched",
            "ingestion_status": "imported",
            "document_id": 81,
            "error": None,
        }],
    })

    dumped = response.model_dump()
    assert "content" not in dumped["items"][0]
    assert "html" not in dumped["items"][0]
```

- [x] **Step 2: Run the tests and verify the missing-module failure**

Run:

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_crawl_schemas.py -q
```

Expected: collection fails with `ModuleNotFoundError: app.schemas.wikipedia_crawls`.

- [x] **Step 3: Implement strict schemas and canonicalization**

Create `app/schemas/wikipedia_crawls.py` with this public surface:

```python
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_wikipedia_category(value: str) -> str:
    stripped = value.strip()
    if not stripped or any(ord(char) < 32 or ord(char) == 127 for char in stripped):
        raise ValueError("category must be a non-empty title without control characters")
    title = (
        stripped[len("category:") :].strip()
        if stripped.casefold().startswith("category:")
        else stripped
    )
    if not title:
        raise ValueError("category title must not be empty")
    parsed = urlsplit(title)
    if parsed.scheme or parsed.netloc or title.startswith("//"):
        raise ValueError("category must be a title, not a URL")
    canonical = f"Category:{title}"
    if len(canonical) > 255:
        raise ValueError("canonical category title must be at most 255 characters")
    return canonical


class WikipediaCrawlRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_default=True,
    )

    category: str = Field(
        default="Category:Featured articles",
        min_length=1,
        max_length=255,
    )
    max_articles: int = Field(default=100, ge=1, le=500)
    max_depth: int = Field(default=0, ge=0, le=2)

    @field_validator("category")
    @classmethod
    def canonicalize_category(cls, value: str) -> str:
        return normalize_wikipedia_category(value)


class WikipediaCrawlItemResponse(BaseModel):
    position: int
    wikipedia_page_id: int
    title: str
    url: str
    fetch_status: str
    ingestion_status: str | None
    document_id: int | None
    error: str | None


class WikipediaCrawlItemListResponse(BaseModel):
    job_id: UUID
    total_results: int
    limit: int
    offset: int
    items: list[WikipediaCrawlItemResponse]
```

- [x] **Step 4: Run the focused schema tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_crawl_schemas.py -q
```

Expected: all crawler schema tests pass.

- [x] **Step 5: Commit and push**

```bash
git add app/schemas/wikipedia_crawls.py tests/unit/test_wikipedia_crawl_schemas.py docs/superpowers/plans/2026-07-21-wikipedia-category-crawler.md
git commit -m "feat: define Wikipedia crawl contracts"
git push origin main
```

### Task 2: Add Wikimedia Runtime Configuration

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `app/core/config.py`
- Modify: `tests/unit/test_config.py`

**Interfaces:**
- Produces: crawler defaults on `Settings` and matching environment overrides.
- Consumes: the existing immutable `Settings` dataclass and `get_settings()`.

- [x] **Step 1: Write failing configuration tests**

Append these assertions to `tests/unit/test_config.py`:

```python
import pytest

from app.core.config import (
    DEFAULT_WIKIPEDIA_ACTION_API_URL,
    DEFAULT_WIKIPEDIA_REST_API_URL,
    DEFAULT_WIKIPEDIA_USER_AGENT,
)


def test_default_wikipedia_settings_are_bounded_and_identifying(monkeypatch):
    for name in (
        "WIKIPEDIA_ACTION_API_URL",
        "WIKIPEDIA_REST_API_URL",
        "WIKIPEDIA_USER_AGENT",
        "WIKIPEDIA_CONCURRENCY",
        "WIKIPEDIA_REQUESTS_PER_SECOND",
        "WIKIPEDIA_REQUEST_TIMEOUT_SECONDS",
        "WIKIPEDIA_MAX_RESPONSE_BYTES",
        "WIKIPEDIA_MAX_CATEGORIES",
        "WIKIPEDIA_FETCH_ATTEMPTS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.wikipedia_action_api_url == DEFAULT_WIKIPEDIA_ACTION_API_URL
    assert settings.wikipedia_rest_api_url == DEFAULT_WIKIPEDIA_REST_API_URL
    assert settings.wikipedia_user_agent == DEFAULT_WIKIPEDIA_USER_AGENT
    assert settings.wikipedia_concurrency == 4
    assert settings.wikipedia_requests_per_second == 2.0
    assert settings.wikipedia_request_timeout_seconds == 30.0
    assert settings.wikipedia_max_response_bytes == 10 * 1024 * 1024
    assert settings.wikipedia_max_categories == 100
    assert settings.wikipedia_fetch_attempts == 3


def test_wikipedia_settings_accept_test_server_overrides(monkeypatch):
    monkeypatch.setenv("WIKIPEDIA_ACTION_API_URL", "http://127.0.0.1:8765/action")
    monkeypatch.setenv("WIKIPEDIA_REST_API_URL", "http://127.0.0.1:8765/rest")
    monkeypatch.setenv("WIKIPEDIA_USER_AGENT", "CrawlerTest/1.0 (test@example.com)")
    monkeypatch.setenv("WIKIPEDIA_CONCURRENCY", "2")
    monkeypatch.setenv("WIKIPEDIA_REQUESTS_PER_SECOND", "50")
    monkeypatch.setenv("WIKIPEDIA_REQUEST_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("WIKIPEDIA_MAX_RESPONSE_BYTES", "4096")
    monkeypatch.setenv("WIKIPEDIA_MAX_CATEGORIES", "7")
    monkeypatch.setenv("WIKIPEDIA_FETCH_ATTEMPTS", "2")

    settings = get_settings()

    assert settings.wikipedia_action_api_url.endswith("/action")
    assert settings.wikipedia_rest_api_url.endswith("/rest")
    assert settings.wikipedia_concurrency == 2
    assert settings.wikipedia_requests_per_second == 50.0
    assert settings.wikipedia_request_timeout_seconds == 2.5
    assert settings.wikipedia_max_response_bytes == 4096
    assert settings.wikipedia_max_categories == 7
    assert settings.wikipedia_fetch_attempts == 2


@pytest.mark.parametrize(
    "user_agent",
    ["", "   ", "python-httpx/0.28", "python-requests/2.32", "curl/8.0"],
)
def test_wikipedia_settings_reject_blank_or_generic_user_agents(
    monkeypatch,
    user_agent,
):
    monkeypatch.setenv("WIKIPEDIA_USER_AGENT", user_agent)

    with pytest.raises(ValueError, match="WIKIPEDIA_USER_AGENT"):
        get_settings()
```

Also parameterize every numeric crawler environment key with zero or a negative
value and assert `ValueError` names that key.

- [x] **Step 2: Run the tests and verify missing settings**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_config.py -q
```

Expected: imports or attribute assertions fail for the crawler settings.

- [x] **Step 3: Correct dependencies and add typed settings**

In `requirements.txt`, replace `httpx2` and add the parser dependencies:

```text
httpx
beautifulsoup4
lxml
```

Add these constants and fields to `app/core/config.py`:

```python
DEFAULT_WIKIPEDIA_ACTION_API_URL = "https://en.wikipedia.org/w/api.php"
DEFAULT_WIKIPEDIA_REST_API_URL = "https://en.wikipedia.org/w/rest.php/v1"
DEFAULT_WIKIPEDIA_USER_AGENT = (
    "SatyamSearchEngineBot/1.0 "
    "(https://github.com/satyamarora26/search-engine)"
)


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str = DEFAULT_REDIS_URL
    celery_broker_url: str = DEFAULT_CELERY_BROKER_URL
    celery_result_backend: str = DEFAULT_CELERY_RESULT_BACKEND
    wikipedia_action_api_url: str = DEFAULT_WIKIPEDIA_ACTION_API_URL
    wikipedia_rest_api_url: str = DEFAULT_WIKIPEDIA_REST_API_URL
    wikipedia_user_agent: str = DEFAULT_WIKIPEDIA_USER_AGENT
    wikipedia_concurrency: int = 4
    wikipedia_requests_per_second: float = 2.0
    wikipedia_request_timeout_seconds: float = 30.0
    wikipedia_max_response_bytes: int = 10 * 1024 * 1024
    wikipedia_max_categories: int = 100
    wikipedia_fetch_attempts: int = 3
```

Populate those fields in `get_settings()` with `int(...)` and `float(...)`
environment conversion. Reject nonpositive concurrency, rate, timeout, response
size, category count, and attempt count through a private `_positive()` helper:

```python
def _positive(name: str, value: int | float) -> int | float:
    if value <= 0:
        raise ValueError(f"{name} must be positive.")
    return value
```

Reject a blank user agent and case-insensitive prefixes `python-httpx`,
`python-requests`, and `curl`. Strip URL and user-agent environment values before
storing them.

- [x] **Step 4: Document environment keys and install dependencies**

Append to `.env.example`:

```text
WIKIPEDIA_ACTION_API_URL=https://en.wikipedia.org/w/api.php
WIKIPEDIA_REST_API_URL=https://en.wikipedia.org/w/rest.php/v1
WIKIPEDIA_USER_AGENT="SatyamSearchEngineBot/1.0 (https://github.com/satyamarora26/search-engine)"
WIKIPEDIA_CONCURRENCY=4
WIKIPEDIA_REQUESTS_PER_SECOND=2
WIKIPEDIA_REQUEST_TIMEOUT_SECONDS=30
WIKIPEDIA_MAX_RESPONSE_BYTES=10485760
WIKIPEDIA_MAX_CATEGORIES=100
WIKIPEDIA_FETCH_ATTEMPTS=3
```

Run:

```bash
/opt/anaconda3/bin/python3 -m pip install -r requirements.txt
```

Expected: HTTPX, BeautifulSoup4, and lxml install successfully.

- [x] **Step 5: Run configuration tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_config.py tests/unit/test_celery_config.py -q
```

Expected: all selected tests pass and existing Celery defaults remain unchanged.

- [x] **Step 6: Commit and push**

```bash
git add requirements.txt .env.example app/core/config.py tests/unit/test_config.py docs/superpowers/plans/2026-07-21-wikipedia-category-crawler.md
git commit -m "feat: configure bounded Wikimedia access"
git push origin main
```

### Task 3: Add Durable Wikipedia Crawl Models And Migration

**Files:**
- Create: `app/models/wikipedia_crawl.py`
- Create: `alembic/versions/20260721_0005_create_wikipedia_crawler.py`
- Create: `tests/unit/test_wikipedia_crawl_models.py`
- Modify: `app/models/job.py`
- Modify: `app/models/__init__.py`
- Modify: `alembic/env.py`
- Modify: `tests/unit/test_job_model.py`

**Interfaces:**
- Produces: `WIKIPEDIA_CRAWL_JOB`, crawl/frontier/page status constants, `WikipediaCrawlRun`, `WikipediaCrawlFrontier`, and `WikipediaCrawlPage`.
- Consumes: existing `Job`, `IngestionItem`, SQLAlchemy `Base`, and revision `20260721_0004`.

- [x] **Step 1: Write failing model and DDL tests**

Create `tests/unit/test_wikipedia_crawl_models.py` with exact column and guard checks:

```python
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.wikipedia_crawl import (
    WikipediaCrawlFrontier,
    WikipediaCrawlPage,
    WikipediaCrawlRun,
)


def test_crawl_run_has_request_and_discovery_checkpoint_columns():
    assert {
        "job_id", "root_category", "max_articles", "max_depth",
        "discovery_complete", "category_limit_reached",
        "created_at", "updated_at",
    } == set(WikipediaCrawlRun.__table__.columns.keys())


def test_frontier_has_durable_breadth_first_checkpoint_columns():
    assert {
        "id", "job_id", "category_title", "depth", "continuation",
        "status", "error", "created_at", "updated_at",
    } == set(WikipediaCrawlFrontier.__table__.columns.keys())


def test_page_has_fetch_and_ingestion_link_columns():
    assert {
        "id", "job_id", "position", "wikipedia_page_id", "title",
        "canonical_url", "fetch_status", "fetch_attempts",
        "ingestion_item_id", "error", "fetched_at", "created_at",
        "updated_at",
    } == set(WikipediaCrawlPage.__table__.columns.keys())


def test_crawler_models_compile_postgresql_constraints_and_foreign_keys():
    sql = "\n".join(
        str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        for model in (WikipediaCrawlRun, WikipediaCrawlFrontier, WikipediaCrawlPage)
    )

    assert "FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE" in sql
    assert "FOREIGN KEY(ingestion_item_id) REFERENCES ingestion_items (id) ON DELETE CASCADE" in sql
    assert "wikipedia_crawl_pages_job_page_key" in sql
    assert "wikipedia_crawl_pages_outcome_check" in sql
```

Extend `tests/unit/test_job_model.py` to assert:

```python
from app.models.job import WIKIPEDIA_CRAWL_JOB

assert WIKIPEDIA_CRAWL_JOB == "wikipedia_crawl"
```

- [x] **Step 2: Run tests and verify the missing models**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_job_model.py tests/unit/test_wikipedia_crawl_models.py -q
```

Expected: collection fails because `app.models.wikipedia_crawl` does not exist.

- [x] **Step 3: Implement the three SQLAlchemy models**

Add `WIKIPEDIA_CRAWL_JOB = "wikipedia_crawl"` to `app/models/job.py`.

Create `app/models/wikipedia_crawl.py` with lowercase status constants:

```python
PENDING_FRONTIER_STATUS = "pending"
COMPLETED_FRONTIER_STATUS = "completed"
FAILED_FRONTIER_STATUS = "failed"
PENDING_FETCH_STATUS = "pending"
FETCHED_FETCH_STATUS = "fetched"
FAILED_FETCH_STATUS = "failed"
```

Use these named constraints and indexes:

```text
wikipedia_crawl_runs_article_limit_check
wikipedia_crawl_runs_depth_check
wikipedia_crawl_frontier_job_category_key
wikipedia_crawl_frontier_depth_check
wikipedia_crawl_frontier_status_check
wikipedia_crawl_frontier_outcome_check
wikipedia_crawl_frontier_job_status_depth_idx
wikipedia_crawl_pages_job_position_key
wikipedia_crawl_pages_job_page_key
wikipedia_crawl_pages_position_check
wikipedia_crawl_pages_attempts_check
wikipedia_crawl_pages_status_check
wikipedia_crawl_pages_outcome_check
wikipedia_crawl_pages_ingestion_item_key
wikipedia_crawl_pages_job_status_position_idx
```

The page outcome constraint must be exactly coherent:

```python
CheckConstraint(
    "(fetch_status = 'pending' and ingestion_item_id is null "
    "and error is null and fetched_at is null) or "
    "(fetch_status = 'fetched' and ingestion_item_id is not null "
    "and error is null and fetched_at is not null) or "
    "(fetch_status = 'failed' and ingestion_item_id is null "
    "and error is not null and fetched_at is null)",
    name="wikipedia_crawl_pages_outcome_check",
)
```

Use PostgreSQL `JSON` for nullable frontier continuation, UUID job keys,
identity bigint row ids, timezone-aware timestamps, and the foreign-key/delete
rules from the design. Export all three models in `app/models/__init__.py` and
import them in `alembic/env.py` so `Base.metadata` is complete.

- [x] **Step 4: Write migration `20260721_0005`**

Create the three tables in dependency order and their two operational indexes.
The migration header must contain:

```python
revision: str = "20260721_0005"
down_revision: str | None = "20260721_0004"
```

Use the same column types, defaults, named constraints, unique constraints, and
foreign-key delete rules as the models. Downgrade in this exact order:

```python
op.drop_index(
    "wikipedia_crawl_pages_job_status_position_idx",
    table_name="wikipedia_crawl_pages",
)
op.drop_table("wikipedia_crawl_pages")
op.drop_index(
    "wikipedia_crawl_frontier_job_status_depth_idx",
    table_name="wikipedia_crawl_frontier",
)
op.drop_table("wikipedia_crawl_frontier")
op.drop_table("wikipedia_crawl_runs")
```

- [x] **Step 5: Run model tests and migration round trip**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_job_model.py tests/unit/test_wikipedia_crawl_models.py -q
alembic upgrade head
alembic current
alembic downgrade 20260721_0004
alembic upgrade head
alembic current
```

Expected: unit tests pass, downgrade reaches `20260721_0004`, and the final
revision is `20260721_0005 (head)`.

- [x] **Step 6: Commit and push**

```bash
git add app/models/job.py app/models/wikipedia_crawl.py app/models/__init__.py alembic/env.py alembic/versions/20260721_0005_create_wikipedia_crawler.py tests/unit/test_job_model.py tests/unit/test_wikipedia_crawl_models.py docs/superpowers/plans/2026-07-21-wikipedia-category-crawler.md
git commit -m "feat: add durable Wikipedia crawl schema"
git push origin main
```

### Task 4: Add Crawl DTOs And Repository Boundaries

**Files:**
- Create: `app/services/wikipedia_types.py`
- Create: `app/repositories/wikipedia_crawls.py`
- Create: `tests/unit/test_wikipedia_crawl_repository.py`
- Modify: `app/repositories/ingestion_items.py`
- Modify: `tests/unit/test_ingestion_item_repository.py`

**Interfaces:**
- Produces: `wikipedia_article_url()`, `WikipediaPageReference`, `WikipediaCategoryReference`, `WikipediaCategoryBatch`, `FetchedWikipediaArticle`, `CrawlRunSnapshot`, `FrontierSnapshot`, `CrawlPageSnapshot`, `CrawlCounts`, and `CrawlItemView`.
- Produces: `WikipediaCrawlRepository` reads, guarded transitions, counts, and pagination.
- Produces: `IngestionItemRepository.stage_at_position(job_id, position, payload)`.
- Consumes: crawler ORM models and existing ingestion statuses.

- [x] **Step 1: Write failing explicit-position and crawl-query tests**

Extend `tests/unit/test_ingestion_item_repository.py`:

```python
def test_stage_at_position_preserves_crawler_discovery_position():
    session = FakeSession()
    repository = repository_type()(session)

    item = repository.stage_at_position(
        JOB_ID,
        17,
        {"title": "BM25", "content": "ranking"},
    )

    assert item.job_id == JOB_ID
    assert item.position == 17
    assert item.status == PENDING_ITEM_STATUS
    assert session.added == [item]
    assert session.flushed is True
```

Create `tests/unit/test_wikipedia_crawl_repository.py` with fake-session SQL
compilation tests proving:

```python
def test_next_frontier_uses_breadth_first_stable_order():
    repository.get_next_pending_frontier(JOB_ID)
    sql = compile_sql(session.statements[0])
    assert "status = 'pending'" in sql
    assert "ORDER BY wikipedia_crawl_frontier.depth ASC" in sql
    assert "wikipedia_crawl_frontier.id ASC" in sql
    assert "LIMIT 1" in sql


def test_pending_pages_use_discovery_order_and_bound():
    repository.list_pending_pages(JOB_ID, limit=20)
    sql = compile_sql(session.statements[0])
    assert "fetch_status = 'pending'" in sql
    assert "ORDER BY wikipedia_crawl_pages.position ASC" in sql
    assert "LIMIT 20" in sql


def test_fetch_transitions_are_guarded_by_pending_status():
    repository.mark_page_failed(9, attempts=3, error="wikipedia_not_found")
    sql = compile_sql(session.statements[0])
    assert "wikipedia_crawl_pages.id = 9" in sql
    assert "wikipedia_crawl_pages.fetch_status = 'pending'" in sql


def test_item_view_query_outer_joins_ingestion_outcomes_and_paginates():
    repository.list_item_views(JOB_ID, limit=25, offset=50)
    sql = compile_sql(session.statements[0])
    assert "LEFT OUTER JOIN ingestion_items" in sql
    assert "ORDER BY wikipedia_crawl_pages.position ASC" in sql
    assert "LIMIT 25" in sql
    assert "OFFSET 50" in sql
```

- [x] **Step 2: Run tests and verify missing interfaces**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_ingestion_item_repository.py tests/unit/test_wikipedia_crawl_repository.py -q
```

Expected: failures for the missing crawler repository and explicit-position
staging method.

- [x] **Step 3: Add immutable shared DTOs**

Create `app/services/wikipedia_types.py` with frozen dataclasses:

```python
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID


def wikipedia_article_url(title: str) -> str:
    encoded = quote(title.replace(" ", "_"), safe="()")
    return f"https://en.wikipedia.org/wiki/{encoded}"


@dataclass(frozen=True)
class WikipediaPageReference:
    page_id: int
    title: str


@dataclass(frozen=True)
class WikipediaCategoryReference:
    page_id: int
    title: str


@dataclass(frozen=True)
class WikipediaCategoryBatch:
    pages: tuple[WikipediaPageReference, ...]
    subcategories: tuple[WikipediaCategoryReference, ...]
    continuation: dict[str, Any] | None


@dataclass(frozen=True)
class FetchedWikipediaArticle:
    title: str
    canonical_url: str
    html: str
    attempts: int


@dataclass(frozen=True)
class CrawlRunSnapshot:
    job_id: UUID
    root_category: str
    max_articles: int
    max_depth: int
    discovery_complete: bool
    category_limit_reached: bool


@dataclass(frozen=True)
class FrontierSnapshot:
    id: int
    category_title: str
    depth: int
    continuation: dict[str, Any] | None


@dataclass(frozen=True)
class CrawlPageSnapshot:
    id: int
    position: int
    wikipedia_page_id: int
    title: str
    canonical_url: str


@dataclass(frozen=True)
class CrawlCounts:
    categories_visited: int
    discovered: int
    fetched: int
    imported: int
    skipped: int
    fetch_failed: int
    ingestion_failed: int

    @property
    def failed(self) -> int:
        return self.fetch_failed + self.ingestion_failed

    @property
    def terminal(self) -> int:
        return (
            self.fetch_failed
            + self.imported
            + self.skipped
            + self.ingestion_failed
        )


@dataclass(frozen=True)
class CrawlItemView:
    position: int
    wikipedia_page_id: int
    title: str
    url: str
    fetch_status: str
    ingestion_status: str | None
    document_id: int | None
    error: str | None
```

- [x] **Step 4: Implement repository reads and guarded writes**

Add to `IngestionItemRepository`:

```python
def stage_at_position(
    self,
    job_id: UUID,
    position: int,
    payload: JsonValue,
) -> IngestionItem:
    item = IngestionItem(
        job_id=job_id,
        position=position,
        payload=payload,
        status=PENDING_ITEM_STATUS,
    )
    self.session.add(item)
    self.session.flush()
    return item
```

Have `stage_many()` call `stage_at_position()` for each enumerated payload so
bulk and crawler staging share one creation path.

Create `WikipediaCrawlRepository(session)` with these exact methods:

```python
create_run(job_id, *, root_category, max_articles, max_depth)
add_frontier(job_id, *, category_title, depth)
get_run(job_id)
get_run_for_update(job_id)
get_frontier_for_update(frontier_id)
get_next_pending_frontier(job_id)
list_page_ids(job_id)
list_category_titles(job_id)
next_page_position(job_id)
count_frontier(job_id)
count_pages(job_id)
has_pending_frontier(job_id)
add_page(job_id, *, position, wikipedia_page_id, title, canonical_url)
list_pending_pages(job_id, *, limit)
get_page_for_update(page_id)
mark_page_fetched(page_id, *, attempts, ingestion_item_id, fetched_at)
mark_page_failed(page_id, *, attempts, error)
list_pending_ingestion_ids(job_id)
counts(job_id)
count_item_views(job_id)
list_item_views(job_id, *, limit, offset)
```

Convert ORM rows to the frozen snapshots before returning from methods used by
short-lived sessions. Guard both fetch transitions with
`fetch_status == PENDING_FETCH_STATUS`. `counts()` must enforce the design
equations by grouping crawl-page and linked ingestion statuses. Define
`categories_visited` as frontiers whose status is completed or failed, plus
pending frontiers with a non-null continuation checkpoint; an untouched queued
frontier is not visited. Define `discovered` as all crawl pages and `fetched` as
pages with `fetch_status == fetched`. Do not count a fetched page as terminal
while its ingestion item remains pending.

For `CrawlItemView.error`, choose `WikipediaCrawlPage.error` first and then the
linked `IngestionItem.error`. Map the model's `canonical_url` column to the
view's `url` field. Validate pagination before issuing SQL.

- [x] **Step 5: Run repository tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_ingestion_item_repository.py tests/unit/test_wikipedia_crawl_repository.py -q
```

Expected: all selected tests pass.

- [x] **Step 6: Commit and push**

```bash
git add app/services/wikipedia_types.py app/repositories/wikipedia_crawls.py app/repositories/ingestion_items.py tests/unit/test_wikipedia_crawl_repository.py tests/unit/test_ingestion_item_repository.py docs/superpowers/plans/2026-07-21-wikipedia-category-crawler.md
git commit -m "feat: add Wikipedia crawl persistence boundaries"
git push origin main
```

### Task 5: Expose Durable Crawl Submission And Item Reports

**Files:**
- Create: `app/services/wikipedia_crawls.py`
- Create: `app/api/v1/crawls.py`
- Create: `tests/unit/test_wikipedia_crawls.py`
- Create: `tests/integration/test_wikipedia_crawl_api.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/api/v1/router.py`

**Interfaces:**
- Produces: `WikipediaCrawlService.enqueue_crawl(request) -> Job`.
- Produces: `WikipediaCrawlService.list_items(job_id, limit, offset) -> tuple[int, list[CrawlItemView]]`.
- Produces: `get_wikipedia_crawl_service()` and the two `/api/v1/crawls/wikipedia` routes.
- Consumes: Task 1 schemas, Task 4 repository, `JobRepository`, and Celery task name `wikipedia.crawl`.

- [x] **Step 1: Write failing service tests**

Create `tests/unit/test_wikipedia_crawls.py` using fake session, job repository,
crawl repository, and task sender. Cover this exact successful transaction:

```python
def test_enqueue_creates_job_run_root_frontier_then_sends_uuid():
    request = WikipediaCrawlRequest(
        category="Physics",
        max_articles=25,
        max_depth=1,
    )

    job = service.enqueue_crawl(request)

    assert jobs.created_with == {
        "job_id": JOB_ID,
        "job_type": WIKIPEDIA_CRAWL_JOB,
        "resource_key": SEARCH_INDEX_RESOURCE,
        "progress_total": None,
        "progress_message": "Waiting for worker",
    }
    assert crawls.run_created_with == {
        "job_id": JOB_ID,
        "root_category": "Category:Physics",
        "max_articles": 25,
        "max_depth": 1,
    }
    assert crawls.frontier_created_with == {
        "job_id": JOB_ID,
        "category_title": "Category:Physics",
        "depth": 0,
    }
    assert session.commits == 1
    assert task.calls == [{"args": [str(JOB_ID)], "task_id": str(JOB_ID)}]
    assert job.id == JOB_ID
```

Also test:

- Active `search_index` owner raises `IndexJobConflictError` before writes.
- Unique-resource `IntegrityError` rolls back and reports the winning owner.
- Other SQLAlchemy failures roll back and become `JobStorageError`.
- Broker failure marks the pending job failed with
  `Could not enqueue background job.` and raises `JobEnqueueError`.
- Failure while recording enqueue failure does not replace `JobEnqueueError`.
- `list_items()` accepts only a `wikipedia_crawl` job and maps storage errors.

- [x] **Step 2: Write failing FastAPI contract tests**

Create `tests/integration/test_wikipedia_crawl_api.py` with a dependency-overridden
fake service. Assert:

```python
def test_submit_returns_202_job_contract():
    response = client.post(
        "/api/v1/crawls/wikipedia",
        json={"category": "Physics", "max_articles": 25, "max_depth": 1},
    )

    assert response.status_code == 202
    assert response.json() == {
        "job_id": str(JOB_ID),
        "status": "PENDING",
        "status_url": f"/api/v1/jobs/{JOB_ID}",
    }
```

Add exact assertions for HTTP `409`, safe `503`, strict `422`, malformed UUID,
pagination bounds, non-crawl `404`, and a page report that omits content and HTML.

- [x] **Step 3: Run tests and verify missing service and routes**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_crawls.py tests/integration/test_wikipedia_crawl_api.py -q
```

Expected: collection fails for missing crawler service/API modules.

- [x] **Step 4: Implement the transactional API-facing service**

Create `app/services/wikipedia_crawls.py` with:

```python
class WikipediaCrawlNotFoundError(Exception):
    pass


class WikipediaCrawlService:
    def __init__(
        self,
        session: Session,
        task: TaskSender,
        *,
        job_id_factory: Callable[[], UUID] = uuid4,
        job_repository: JobRepository | None = None,
        crawl_repository: WikipediaCrawlRepository | None = None,
    ) -> None: ...

    def enqueue_crawl(self, request: WikipediaCrawlRequest) -> Job: ...

    def list_items(
        self,
        job_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[int, list[CrawlItemView]]: ...
```

Follow `BulkIngestionService` transaction and error patterns. Create the job,
run, and depth-zero root frontier before one commit. Send the task only after
commit with the durable UUID as both argument and task id. On a resource-index
race, roll back, load the active resource owner, and raise
`IndexJobConflictError`; never stage a partial crawl request.

`list_items()` must first load and type-check the job, then call
`count_item_views()` and `list_item_views()` in stable position order.

- [x] **Step 5: Register dependencies and routes**

Add to `app/api/dependencies.py`:

```python
def get_wikipedia_crawl_service(
    session: Session = Depends(get_db_session),
) -> WikipediaCrawlService:
    task = celery_app.signature("wikipedia.crawl")
    return WikipediaCrawlService(session, task)
```

Create `app/api/v1/crawls.py` with `APIRouter(prefix="/crawls/wikipedia",
tags=["crawls"])`. The POST route accepts `WikipediaCrawlRequest`, returns
`JobAcceptedResponse` with HTTP `202`, and maps conflict/infrastructure errors
exactly like the bulk route. The GET `/{job_id}/items` route uses `limit=100`
with bounds 1..100 and nonnegative `offset`, then returns
`WikipediaCrawlItemListResponse`.

Register this router in `app/api/v1/router.py` before no conflicting dynamic
route is introduced.

- [x] **Step 6: Run service and API tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_crawls.py tests/integration/test_wikipedia_crawl_api.py tests/integration/test_bulk_ingestion_api.py -q
```

Expected: crawler tests pass and the bulk API contract remains green.

- [x] **Step 7: Commit and push**

```bash
git add app/services/wikipedia_crawls.py app/api/v1/crawls.py app/api/dependencies.py app/api/v1/router.py tests/unit/test_wikipedia_crawls.py tests/integration/test_wikipedia_crawl_api.py docs/superpowers/plans/2026-07-21-wikipedia-category-crawler.md
git commit -m "feat: expose durable Wikipedia crawl API"
git push origin main
```

### Task 6: Extract Searchable Prose From Parsoid HTML

**Files:**
- Create: `app/services/wikipedia_extraction.py`
- Create: `tests/fixtures/wikipedia/article.html`
- Create: `tests/unit/test_wikipedia_extraction.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `WikipediaExtractionError(code: str)`.
- Produces: `extract_wikipedia_text(html: str, *, minimum_characters: int = 100) -> str`.
- Consumes: BeautifulSoup4 and lxml installed in Task 2.

- [x] **Step 1: Add a representative HTML fixture**

Create `tests/fixtures/wikipedia/article.html` containing a body with:

```html
<!doctype html>
<html><body>
  <section data-mw-section-id="0">
    <p>Information retrieval finds material relevant to an information need.</p>
    <figure><figcaption>Decorative image caption</figcaption></figure>
    <table><tr><td>Infobox noise</td></tr></table>
  </section>
  <section data-mw-section-id="1">
    <h2>Ranking models</h2>
    <p>BM25 balances term frequency with document length normalization.
      <sup class="reference">[1]</sup>
    </p>
    <ul><li>Probabilistic relevance scoring</li></ul>
  </section>
  <section data-mw-section-id="2">
    <h2>References</h2>
    <ol class="references"><li>Reference noise that must disappear.</li></ol>
  </section>
</body></html>
```

- [x] **Step 2: Write failing extraction tests**

Create `tests/unit/test_wikipedia_extraction.py`:

```python
from pathlib import Path

import pytest

from app.services.wikipedia_extraction import (
    WikipediaExtractionError,
    extract_wikipedia_text,
)

FIXTURE = Path("tests/fixtures/wikipedia/article.html")


def test_extracts_prose_headings_and_meaningful_lists_without_noise():
    text = extract_wikipedia_text(FIXTURE.read_text(encoding="utf-8"))

    assert "Information retrieval finds material" in text
    assert "Ranking models" in text
    assert "BM25 balances term frequency" in text
    assert "Probabilistic relevance scoring" in text
    assert "Decorative image caption" not in text
    assert "Infobox noise" not in text
    assert "Reference noise" not in text
    assert "[1]" not in text


def test_preserves_unicode_and_normalizes_horizontal_whitespace():
    html = "<html><body><p>Naive   cafe search supports हिंदी text and useful content that comfortably exceeds the minimum extraction length for this focused test.</p></body></html>"

    text = extract_wikipedia_text(html)

    assert "Naive cafe search supports हिंदी text" in text
    assert "  " not in text


@pytest.mark.parametrize(
    ("html", "code"),
    [
        ("<html><head></head></html>", "missing_article_body"),
        ("<html><body><p>short</p></body></html>", "content_too_short"),
    ],
)
def test_rejects_missing_or_short_article_content(html, code):
    with pytest.raises(WikipediaExtractionError) as caught:
        extract_wikipedia_text(html)
    assert caught.value.code == code
```

- [x] **Step 3: Run tests and verify the missing extractor**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_extraction.py -q
```

Expected: collection fails for missing `wikipedia_extraction`.

- [x] **Step 4: Implement pure deterministic extraction**

Create `app/services/wikipedia_extraction.py`. Define the excluded headings as
case-folded exact names:

```python
EXCLUDED_SECTION_HEADINGS = {
    "references",
    "notes",
    "citations",
    "bibliography",
    "external links",
    "further reading",
    "see also",
}
REMOVAL_SELECTORS = (
    "script", "style", "nav", "figure", "table", "sup.reference",
    ".mw-ref", "ol.references", ".references",
)
```

Parse with `BeautifulSoup(html, "lxml")`, require `soup.body`, remove every
matching node, and remove a complete `section` when its first `h2` or `h3`
heading matches the excluded set. Collect remaining `h2`, `h3`, `p`, and `li`
elements while skipping elements nested under another collected list item.

Normalize each chunk with:

```python
normalized = " ".join(node.get_text(" ", strip=True).split())
```

Join nonblank chunks with two newlines. Raise `WikipediaExtractionError` with
only `missing_article_body`, `empty_article_content`, or `content_too_short`.
Do not retain the original HTML on the exception.

Require `beautifulsoup4>=4.13,<5` so its lxml adapter does not use the removed
`strip_cdata` parser option present in BeautifulSoup 4.12.

- [x] **Step 5: Run extractor tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_extraction.py -q
```

Expected: all extractor tests pass.

- [x] **Step 6: Commit and push**

```bash
git add app/services/wikipedia_extraction.py tests/fixtures/wikipedia/article.html tests/unit/test_wikipedia_extraction.py requirements.txt docs/superpowers/plans/2026-07-21-wikipedia-category-crawler.md
git commit -m "feat: extract searchable Wikipedia prose"
git push origin main
```

### Task 7: Build The Policy-Compliant Wikimedia Client

**Files:**
- Create: `app/services/wikipedia_client.py`
- Create: `tests/unit/test_wikipedia_client.py`

**Interfaces:**
- Produces: `WikipediaRequestError`, `WikipediaTransientError`, and `WikipediaPermanentError`, each with safe `code` and `attempts`.
- Produces: `AsyncRequestRateLimiter.wait()`.
- Produces: async context manager `WikipediaClient` with `discover_category()` and `fetch_article()`.
- Produces: `create_wikipedia_client(settings: Settings | None = None) -> WikipediaClient`.
- Consumes: Task 2 settings and Task 4 source DTOs.

- [x] **Step 1: Write failing Action API parsing and URL tests**

Create `tests/unit/test_wikipedia_client.py` with `httpx.MockTransport`. Keep the
test environment independent of an async pytest plugin: every async scenario is
an inner coroutine executed by a normal test through `asyncio.run()`. Define
this reusable local client helper after importing `asyncio`, `httpx`,
`dataclasses.replace`, `get_settings`, and the client/source DTO symbols:

```python
def client_for_handler(handler, **client_kwargs):
    settings = replace(
        get_settings(),
        wikipedia_action_api_url="https://en.wikipedia.org/w/api.php",
        wikipedia_rest_api_url="https://en.wikipedia.org/w/rest.php/v1",
        wikipedia_user_agent="CrawlerTest/1.0 (test@example.com)",
        wikipedia_requests_per_second=1000.0,
    )
    return WikipediaClient(
        settings,
        transport=httpx.MockTransport(handler),
        **client_kwargs,
    )
```

The first response must contain both namespaces and continuation:

```python
ACTION_RESPONSE = {
    "continue": {"cmcontinue": "page|next", "continue": "-||"},
    "query": {
        "categorymembers": [
            {"pageid": 10, "ns": 0, "title": "BM25"},
            {"pageid": 20, "ns": 14, "title": "Category:Search algorithms"},
        ]
    },
}


def test_discovery_sends_structured_parameters_and_parses_namespaces():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=ACTION_RESPONSE, request=request)

    async def scenario():
        async with client_for_handler(handler) as client:
            return await client.discover_category(
                "Category:Information retrieval",
                {"cmcontinue": "page|start", "continue": "-||"},
            )

    batch = asyncio.run(scenario())

    assert batch.pages == (WikipediaPageReference(page_id=10, title="BM25"),)
    assert batch.subcategories == (
        WikipediaCategoryReference(
            page_id=20,
            title="Category:Search algorithms",
        ),
    )
    assert batch.continuation == ACTION_RESPONSE["continue"]
```

Assert the request includes `action=query`, `list=categorymembers`,
`cmnamespace=0|14`, `cmtype=page|subcat`, `cmsort=sortkey`, `cmdir=asc`,
`cmlimit=50`, `format=json`, and `formatversion=2` plus the opaque continuation.

Add a REST test proving `?`, slash, Unicode, and spaces in a title are percent
encoded and the returned canonical URL uses `/wiki/<encoded-title>`.

- [x] **Step 2: Write failing traffic-control and error tests**

Add deterministic injected clock/sleep/jitter tests for:

- Four requests may be in flight but the fifth waits for a semaphore slot.
- Request starts are separated by at least `1 / requests_per_second`.
- HTTP `429` honors numeric `Retry-After` before succeeding.
- An HTTP-date `Retry-After` value is parsed relative to an injected UTC clock.
- Timeout, `408`, `429`, and `500` exhaust after exactly three attempts and
  raise `WikipediaTransientError(code="wikipedia_request_failed", attempts=3)`.
- `404` raises `WikipediaPermanentError(code="wikipedia_not_found", attempts=1)`.
- Other nonretryable `4xx` responses raise
  `WikipediaPermanentError(code="wikipedia_request_rejected", attempts=1)`.
- A body larger than the configured byte limit raises
  `WikipediaPermanentError(code="wikipedia_response_too_large", attempts=1)`.
- Wrong JSON/HTML content type and malformed Action JSON raise stable permanent
  response errors without including the body.
- A redirect to another host raises `wikipedia_redirect_rejected` before that
  external URL is requested.
- Every request contains the configured descriptive `User-Agent` and no cookie,
  including after a response attempts to set one before a same-host redirect.
- `caplog` records request attempt/retry/completion events with operation,
  endpoint host, status, attempt, duration, and outcome fields, while a
  distinctive JSON body or HTML phrase never appears in any log message or
  record field.

Use the same `asyncio.run()` convention for every retry, limiter, concurrency,
streaming, redirect, and logging scenario in this file.

- [x] **Step 3: Run tests and verify the client is missing**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_client.py -q
```

Expected: collection fails for missing `wikipedia_client`.

- [x] **Step 4: Implement rate limiting and safe errors**

Use these public error contracts:

```python
class WikipediaRequestError(Exception):
    def __init__(self, code: str, *, attempts: int) -> None:
        super().__init__(code)
        self.code = code
        self.attempts = attempts


class WikipediaTransientError(WikipediaRequestError):
    pass


class WikipediaPermanentError(WikipediaRequestError):
    pass
```

Implement `AsyncRequestRateLimiter` with one `asyncio.Lock`, injected monotonic
clock, injected async sleep, and `next_allowed_start`. Its `wait()` reserves one
start interval while holding the lock, sleeps only for the calculated delay, and
never uses wall-clock time.

Use these injectable constructor boundaries:

```python
class AsyncRequestRateLimiter:
    def __init__(
        self,
        requests_per_second: float,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None: ...


class WikipediaClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] = utc_now,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None: ...
```

Define `utc_now()` as a module helper returning
`datetime.now(timezone.utc)`. Create one
`httpx.AsyncClient(follow_redirects=False)` and one
`asyncio.Semaphore(settings.wikipedia_concurrency)`. Use a module logger and
structured event names `wikipedia_request_attempt`, `wikipedia_request_retry`,
and `wikipedia_request_complete`; attach only operation, endpoint host,
status code, attempt, delay, duration in milliseconds, and outcome metadata.
Never attach response bytes, decoded JSON, HTML, or article content.

- [x] **Step 5: Implement bounded streamed requests and retries**

For each HTTP attempt:

1. Wait on the shared request-rate limiter.
2. Acquire the shared concurrency semaphore.
3. Stream the response and stop once accumulated bytes exceed the configured
   maximum.
4. Release the semaphore before any retry sleep.

Follow at most five redirects manually. Resolve `Location` against the current
URL, then require the same scheme and host as the configured endpoint before
issuing the redirected request.

Classify status codes exactly as the tests require. Retry transient HTTPX
transport/timeout errors and retryable statuses up to the configured attempt
count. Before another attempt, sleep for a valid `Retry-After`; otherwise sleep
for `jitter(0.0, float(2**attempt))`. Do not retry permanent status, content-type,
size, redirect, or decoding errors.

- [x] **Step 6: Implement discovery and article methods**

Define:

```python
async def discover_category(
    self,
    category: str,
    continuation: dict[str, Any] | None,
) -> WikipediaCategoryBatch: ...

async def fetch_article(self, title: str) -> FetchedWikipediaArticle: ...


def create_wikipedia_client(
    settings: Settings | None = None,
) -> WikipediaClient:
    return WikipediaClient(settings or get_settings())
```

`discover_category()` validates that `query.categorymembers` is a list and that
every accepted member has integer `pageid`, integer `ns`, and string `title`.
Ignore namespaces other than zero and fourteen. Preserve the complete response
`continue` object or return null.

`fetch_article()` percent-encodes the path title with no slash treated as safe,
requires `text/html`, and returns the discovered title, decoded UTF-8 HTML,
actual attempt count, and the canonical URL from the shared
`wikipedia_article_url()` helper in `app/services/wikipedia_types.py`.

- [x] **Step 7: Run client tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_client.py -q
```

Expected: all client tests pass without live network access.

- [x] **Step 8: Commit and push**

```bash
git add app/services/wikipedia_client.py tests/unit/test_wikipedia_client.py docs/superpowers/plans/2026-07-21-wikipedia-category-crawler.md
git commit -m "feat: add bounded Wikimedia API client"
git push origin main
```

### Task 8: Implement Resumable Breadth-First Discovery

**Files:**
- Create: `app/services/wikipedia_crawl_store.py`
- Create: `app/services/wikipedia_discovery.py`
- Create: `tests/unit/test_wikipedia_discovery.py`

**Interfaces:**
- Produces: `WikipediaCrawlStateError`, `DiscoveryCheckpoint`, and discovery methods on `WikipediaCrawlStore`.
- Produces: `WikipediaDiscoveryRunner.run(job_id) -> int` returning discovered count.
- Consumes: Task 4 repository/DTOs and Task 7 `WikipediaClient.discover_category()`.

- [x] **Step 1: Write failing breadth-first runner tests**

Create fake store and async fake client tests in
`tests/unit/test_wikipedia_discovery.py`. Cover this call order:

```python
def test_runner_resumes_continuation_then_moves_breadth_first():
    store.frontiers = [
        FrontierSnapshot(
            id=1,
            category_title="Category:Root",
            depth=0,
            continuation={"cmcontinue": "root-next", "continue": "-||"},
        ),
        FrontierSnapshot(
            id=2,
            category_title="Category:Child",
            depth=1,
            continuation=None,
        ),
    ]

    async def scenario():
        return await WikipediaDiscoveryRunner(store, client).run(JOB_ID)

    count = asyncio.run(scenario())

    assert client.calls == [
        ("Category:Root", {"cmcontinue": "root-next", "continue": "-||"}),
        ("Category:Child", None),
    ]
    assert count == store.final_discovered_count
```

Also test:

- Duplicate page ids receive one deterministic position.
- Duplicate category titles receive one frontier row.
- Depth-zero ignores subcategories; depth one queues only immediate children.
- `max_articles` stops mid-response at the deterministic first N unique pages.
- A 101st eligible category is suppressed and persists
  `category_limit_reached=True` while existing frontier work can finish.
- Natural completion at exactly 100 categories leaves the flag false.
- A checkpoint commits members and continuation together.
- A simulated commit failure rolls back both members and continuation.
- The store session is closed before the fake client is awaited.
- A previously complete run performs no HTTP request.
- Structured discovery logs carry `job_id`, phase, category, depth, outcome,
  and discovered count without serializing the Action API response.

Run every async fake scenario through an inner coroutine and `asyncio.run()`.

- [x] **Step 2: Run tests and verify missing discovery components**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_discovery.py -q
```

Expected: collection fails for missing store/discovery modules.

- [x] **Step 3: Implement short-session discovery storage**

Create `app/services/wikipedia_crawl_store.py` with a `SessionLocal`-backed
`WikipediaCrawlStore`. Define the state contracts and constructor exactly:

```python
class WikipediaCrawlStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoveryCheckpoint:
    discovered_count: int
    discovery_complete: bool
    category_limit_reached: bool


class WikipediaCrawlStore:
    def __init__(
        self,
        session_factory=SessionLocal,
        repository_factory=WikipediaCrawlRepository,
        ingestion_repository_factory=IngestionItemRepository,
        max_categories: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository_factory = repository_factory
        self.ingestion_repository_factory = ingestion_repository_factory
        self.max_categories = (
            get_settings().wikipedia_max_categories
            if max_categories is None
            else max_categories
        )
```

Its discovery surface is:

```python
def get_run(self, job_id: UUID) -> CrawlRunSnapshot: ...
def get_counts(self, job_id: UUID) -> CrawlCounts: ...
def get_next_frontier(self, job_id: UUID) -> FrontierSnapshot | None: ...
def checkpoint_discovery(
    self,
    job_id: UUID,
    frontier_id: int,
    batch: WikipediaCategoryBatch,
) -> DiscoveryCheckpoint: ...
def complete_empty_frontier(self, job_id: UUID) -> int: ...
```

Each read owns and closes one session. `checkpoint_discovery()` owns one session
and transaction, locks the run and current frontier, reloads existing page ids
and category titles, and applies the batch in response order.

Import `wikipedia_article_url()` from `app/services/wikipedia_types.py` whenever
a discovered page is persisted; do not define another canonical URL builder.

Always checkpoint the current frontier's returned continuation or completion,
even when the article limit makes the run complete. Set
`category_limit_reached` only when an otherwise eligible unique subcategory is
suppressed. Flush before checking whether another pending frontier remains.
Commit on success, roll back on every exception, and convert ORM rows to frozen
snapshots before closing sessions. Raise `WikipediaCrawlStateError` with one of
`crawl_run_not_found`, `crawl_frontier_not_found`, `crawl_page_not_found`, or
`crawl_state_conflict` when a required row is absent or a discovery guarded
transition does not affect exactly one expected row. Unit tests inject a lower
`max_categories`; production reads the configured default.

`complete_empty_frontier()` locks the run, verifies no pending frontier remains,
sets `discovery_complete=True`, commits, and returns the durable discovered
count. A pending frontier at that point raises `crawl_state_conflict` instead of
silently truncating discovery.

- [x] **Step 4: Implement the asynchronous discovery loop**

Create `app/services/wikipedia_discovery.py`:

```python
class WikipediaDiscoveryRunner:
    def __init__(
        self,
        store: WikipediaCrawlStore,
        client: WikipediaClient,
    ) -> None:
        self.store = store
        self.client = client

    async def run(self, job_id: UUID) -> int:
        while True:
            run = self.store.get_run(job_id)
            if run.discovery_complete:
                return self.store.get_counts(job_id).discovered
            frontier = self.store.get_next_frontier(job_id)
            if frontier is None:
                return self.store.complete_empty_frontier(job_id)
            batch = await self.client.discover_category(
                frontier.category_title,
                frontier.continuation,
            )
            self.store.checkpoint_discovery(job_id, frontier.id, batch)
```

The store method returns and closes before the await. Do not catch Wikimedia
request errors here; the Celery boundary owns whole-task discovery retries. Log
`wikipedia_discovery_started`, `wikipedia_discovery_checkpointed`, and
`wikipedia_discovery_completed` with structured `job_id`, `phase="discovery"`,
category, depth, outcome, and discovered-count fields. Never log the response
batch or its raw JSON.

- [x] **Step 5: Run discovery tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_discovery.py tests/unit/test_wikipedia_crawl_repository.py -q
```

Expected: all discovery and repository tests pass.

- [x] **Step 6: Commit and push**

```bash
git add app/services/wikipedia_crawl_store.py app/services/wikipedia_discovery.py tests/unit/test_wikipedia_discovery.py docs/superpowers/plans/2026-07-21-wikipedia-category-crawler.md
git commit -m "feat: checkpoint Wikipedia category discovery"
git push origin main
```

### Task 9: Fetch, Extract, And Stage Discovered Pages

**Files:**
- Create: `app/services/wikipedia_fetching.py`
- Create: `tests/unit/test_wikipedia_fetching.py`
- Modify: `app/services/wikipedia_crawl_store.py`

**Interfaces:**
- Produces: fetch/staging methods on `WikipediaCrawlStore`.
- Produces: `WikipediaFetchRunner.run(job_id, progress_callback) -> None`.
- Consumes: pending page snapshots, Task 6 extractor, Task 7 client, and explicit-position ingestion staging.

- [ ] **Step 1: Write failing fetch-phase tests**

Create `tests/unit/test_wikipedia_fetching.py` with async fakes. Cover:

```python
def test_fetches_batch_concurrently_then_stages_normalized_payloads():
    store.pending_batches = [[FIRST_PAGE, SECOND_PAGE], []]

    async def scenario():
        await WikipediaFetchRunner(
            store,
            client,
            extractor=lambda html: f"normalized {html} content long enough",
        ).run(JOB_ID, progress_callback=progress.append)

    asyncio.run(scenario())

    assert client.started_before_release == [FIRST_PAGE.title, SECOND_PAGE.title]
    assert store.staged == [
        (
            FIRST_PAGE.id,
            1,
            {
                "title": FIRST_PAGE.title,
                "content": "normalized first html content long enough",
                "url": FIRST_PAGE.canonical_url,
            },
        ),
        (
            SECOND_PAGE.id,
            1,
            {
                "title": SECOND_PAGE.title,
                "content": "normalized second html content long enough",
                "url": SECOND_PAGE.canonical_url,
            },
        ),
    ]
```

Add tests proving:

- At most 20 pending page records are scheduled per gather batch.
- `WikipediaRequestError.code` and attempts become one terminal fetch failure.
- `WikipediaExtractionError.code` becomes a terminal failure with the successful
  HTTP attempt count.
- Unexpected exceptions propagate and leave the page pending.
- A redelivery lists only still-pending pages and never restages fetched pages.
- Progress callback receives the durable terminal count after each persisted
  result.
- No store session remains open while the fake client waits.
- Structured page-outcome logs include `job_id`, phase, page id, attempts,
  discovery position, outcome, and safe error code, while distinctive HTML and
  extracted-content phrases never occur in `caplog`.

Run every async fake scenario through an inner coroutine and `asyncio.run()`.

- [ ] **Step 2: Run tests and verify missing fetching behavior**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_fetching.py -q
```

Expected: collection fails for missing `wikipedia_fetching`.

- [ ] **Step 3: Extend the crawl store with atomic page transitions**

Add these methods to `WikipediaCrawlStore`:

```python
def list_pending_pages(
    self,
    job_id: UUID,
    *,
    limit: int = 20,
) -> list[CrawlPageSnapshot]: ...

def stage_fetched_page(
    self,
    page_id: int,
    *,
    attempts: int,
    payload: dict[str, str],
) -> None: ...

def fail_page(
    self,
    page_id: int,
    *,
    attempts: int,
    error: str,
) -> None: ...

def terminal_count(self, job_id: UUID) -> int: ...
```

`stage_fetched_page()` locks the pending crawl page, calls
`IngestionItemRepository.stage_at_position()` with the crawl job and discovery
position, then marks the page fetched with `datetime.now(timezone.utc)` in the
same transaction. `fail_page()` performs only the guarded page transition.
Both methods return without changing an already terminal row, commit success,
roll back errors, sanitize error strings to at most 300 characters, and close
their sessions.

- [ ] **Step 4: Implement bounded gather and isolated outcomes**

Create `app/services/wikipedia_fetching.py` with a private immutable fetch result
and this public shape:

```python
class WikipediaFetchRunner:
    def __init__(self, store, client, *, extractor=extract_wikipedia_text): ...

    async def run(
        self,
        job_id: UUID,
        *,
        progress_callback: Callable[[int], None],
    ) -> None: ...
```

For each list of at most 20 pending pages, create one coroutine per page and use
`asyncio.gather()` without sharing sessions. A successful coroutine returns
attempt count and normalized payload. Convert only expected
`WikipediaRequestError` and `WikipediaExtractionError` into typed failure
results; let all other exceptions escape.

Persist each gathered result in original page order. After every store commit,
call `progress_callback(store.terminal_count(job_id))`. Loop until the store
returns no pending pages. Log one `wikipedia_page_outcome` event per persisted
result with structured `job_id`, `phase="fetch"`, page id, attempts, outcome,
discovery position, and safe error code. Never include HTML, extracted content,
or payloads in log messages or metadata.

- [ ] **Step 5: Run fetch and extraction tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_fetching.py tests/unit/test_wikipedia_extraction.py tests/unit/test_wikipedia_client.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit and push**

```bash
git add app/services/wikipedia_fetching.py app/services/wikipedia_crawl_store.py tests/unit/test_wikipedia_fetching.py
git commit -m "feat: stage fetched Wikipedia articles"
git push origin main
```

### Task 10: Orchestrate Ingestion, Completion, And Index Publication

**Files:**
- Create: `app/services/wikipedia_crawl_runner.py`
- Create: `tests/unit/test_wikipedia_crawl_runner.py`
- Modify: `app/services/wikipedia_crawl_store.py`

**Interfaces:**
- Produces: `WikipediaCrawlCompletionError` and `WikipediaCrawlRunner.run(job_id) -> dict[str, Any]`.
- Consumes: `JobTracker`, discovery/fetch runners, `IngestionItemProcessor`, crawl counts, snapshot rebuild, and active-version store.

- [ ] **Step 1: Write failing lifecycle and progress tests**

Create `tests/unit/test_wikipedia_crawl_runner.py` with fake tracker, store, client,
processor, discovery phase, fetching phase, rebuild, and snapshot store. Inject
the phase fakes through `discovery_factory` and `fetching_factory`, then prove
the full happy-path call order:

```python
def test_runner_claims_discovers_fetches_ingests_rebuilds_and_succeeds():
    result = runner.run(JOB_ID)

    assert tracker.claimed_with == {
        "progress_current": 0,
        "progress_total": None,
        "progress_message": "Discovering Wikipedia articles",
    }
    assert discovery.calls == [JOB_ID]
    assert fetching.calls == [JOB_ID]
    assert processor.processed_ids == [71, 72, 73]
    assert rebuild.calls == [f"redis-{JOB_ID}"]
    assert result == SUCCESS_RESULT
    assert tracker.success_with == {
        "result": SUCCESS_RESULT,
        "progress_total": 5,
        "progress_message": "Wikipedia crawl completed",
    }
```

Use a four-page result fixture containing two imports, one duplicate skip, one
fetch failure, one visited category, and one rebuilt index. Assert progress total
five and current values derived from durable terminal counts rather than loop
counters. Assert the exact transition messages for discovery, fetching,
per-article ingestion, rebuild or no-change publication, and completion.

Add tests for:

- A started job resumes without a second claim.
- A completed discovery skips Action API calls.
- A successful redelivery returns stored result without opening an HTTP client.
- Missing, wrong-type, and already-failed jobs are rejected without work.
- An unclaimable pending job is rejected.
- Zero discovered pages raises `WikipediaCrawlCompletionError`.
- Every page fetch-failed raises completion error before ingestion/rebuild.
- All fetched ingestion outcomes failed raises completion error.
- Duplicate-only success uses the current active version and skips rebuild.
- One import triggers exactly one rebuild despite sibling failures.
- Rebuild failure propagates without successful completion.
- Final result satisfies all three count equations and carries
  `category_limit_reached` from the durable run.
- Structured phase logs contain job id, phase, outcome, and numeric counts but
  never an ingestion payload, extracted content, or HTML.

- [ ] **Step 2: Run tests and verify the runner is missing**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_crawl_runner.py -q
```

Expected: collection fails for missing `wikipedia_crawl_runner`.

- [ ] **Step 3: Complete store reads required by orchestration**

Add to `WikipediaCrawlStore`:

```python
def list_pending_ingestion_ids(self, job_id: UUID) -> list[int]: ...
```

The method opens one fresh session, delegates to the repository, returns plain
integer ids, and closes the session. Use the `get_counts()` store method added
in Task 8. Keep `get_run()` as the source of root category, request limits, and
the category-limit flag.

- [ ] **Step 4: Implement the resumable runner**

Create `app/services/wikipedia_crawl_runner.py` with this constructor boundary:

```python
class WikipediaCrawlRunner:
    def __init__(
        self,
        tracker: JobTracker | None = None,
        store: WikipediaCrawlStore | None = None,
        processor: IngestionItemProcessor | None = None,
        client_factory: Callable[[], WikipediaClient] = create_wikipedia_client,
        discovery_factory: Callable[
            [WikipediaCrawlStore, WikipediaClient], WikipediaDiscoveryRunner
        ] = WikipediaDiscoveryRunner,
        fetching_factory: Callable[
            [WikipediaCrawlStore, WikipediaClient], WikipediaFetchRunner
        ] = WikipediaFetchRunner,
        rebuild: Callable[
            [str], dict[str, Any]
        ] = rebuild_search_index_snapshot,
        snapshot_store: RedisSearchIndexStore | None = None,
    ) -> None:
        self.tracker = tracker or JobTracker()
        self.store = store or WikipediaCrawlStore()
        self.processor = processor or IngestionItemProcessor()
        self.client_factory = client_factory
        self.discovery_factory = discovery_factory
        self.fetching_factory = fetching_factory
        self.rebuild = rebuild
        self.snapshot_store = (
            snapshot_store or create_redis_search_index_store()
        )
```

`run()` calls `asyncio.run(self._run(job_id))`. `_run()` must:

1. Load and type-check the durable job.
2. Return stored result for `SUCCESS`; reject `FAILURE`.
3. Claim `PENDING` with unknown total and discovery message.
4. Open one async client context and create discovery/fetch runners from the two
   injected factories using the shared store and client.
5. Run discovery unless the durable run is already discovery-complete.
6. Fail when discovered count is zero.
7. Set progress total to `discovered + 1` and message
   `Fetching Wikipedia articles`.
8. Run fetching with a callback that persists the durable terminal count as
   current, retains total `discovered + 1`, and keeps the fetching message.
9. Fail when fetched count is zero.
10. Set message `Ingesting Wikipedia articles` and process only pending linked
    ingestion ids in position order.
11. After every item, reload durable counts and persist terminal progress with
    `Processed article X of N`, where both values come from those counts.
12. Fail unless at least one item imported or duplicate-skipped.
13. At current `discovered`, set `Rebuilding search index` and rebuild
    `redis-<job-id>` when imports exist; otherwise set
    `No index changes required` and read the active version.
14. Reload both run and counts after publication, build the exact result
    dictionary from that fresh durable state, and mark success at total.

Use this result construction without alternate key names:

```python
result = {
    "root_category": run.root_category,
    "max_articles": run.max_articles,
    "max_depth": run.max_depth,
    "categories_visited": counts.categories_visited,
    "category_limit_reached": run.category_limit_reached,
    "discovered_count": counts.discovered,
    "fetched_count": counts.fetched,
    "imported_count": counts.imported,
    "duplicate_skipped_count": counts.skipped,
    "fetch_failed_count": counts.fetch_failed,
    "ingestion_failed_count": counts.ingestion_failed,
    "failed_count": counts.failed,
    "index_rebuilt": index_rebuilt,
    "index_version": index_version,
}
```

Raise `JobTransitionError` for durable state/type violations and
`WikipediaCrawlCompletionError` for the three unusable-corpus conditions. The
Celery boundary records the public job failure. Emit `wikipedia_crawl_phase`
for discovery, fetch, ingestion, and publication transitions, then
`wikipedia_crawl_completed` for the final result. Attach only structured job
id, phase, outcome, and numeric count fields; never log page payloads, HTML, or
content. Use `caplog` to enforce that boundary in runner tests.

- [ ] **Step 5: Run orchestration and existing ingestion tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_wikipedia_crawl_runner.py tests/unit/test_document_ingestion.py tests/unit/test_bulk_ingestion_runner.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit and push**

```bash
git add app/services/wikipedia_crawl_runner.py app/services/wikipedia_crawl_store.py tests/unit/test_wikipedia_crawl_runner.py
git commit -m "feat: run durable Wikipedia crawl lifecycle"
git push origin main
```

### Task 11: Add Crash-Safe Celery Execution

**Files:**
- Create: `app/workers/wikipedia_tasks.py`
- Create: `tests/unit/test_worker_wikipedia_tasks.py`
- Modify: `app/workers/celery_app.py`
- Modify: `tests/unit/test_celery_config.py`

**Interfaces:**
- Produces: Celery task `wikipedia.crawl` and `execute_wikipedia_crawl_attempt()`.
- Consumes: `WikipediaCrawlRunner`, `PostgresAdvisoryLock`, `JobTracker`, and transient infrastructure errors.

- [ ] **Step 1: Write failing worker-boundary tests**

Create `tests/unit/test_worker_wikipedia_tasks.py` following the existing bulk
task fakes. Assert:

```python
def test_task_configuration_supports_worker_crash_redelivery():
    assert wikipedia_crawl_task.name == "wikipedia.crawl"
    assert wikipedia_crawl_task.acks_late is True
    assert wikipedia_crawl_task.reject_on_worker_lost is True
    assert wikipedia_crawl_task.max_retries == 3


def test_task_rejects_job_id_different_from_celery_task_id():
    with pytest.raises(RuntimeError, match="Celery task id does not match"):
        wikipedia_crawl_task.apply(
            args=[str(JOB_ID)],
            task_id=str(OTHER_JOB_ID),
            throw=True,
        )
```

Add tests proving:

- Successful execution runs once under the UUID advisory lock.
- A busy lock raises Celery `Ignore` without running or failing the real job.
- `OperationalError`, Redis connection/timeout, and
  `WikipediaTransientError` retry at 2, 4, and 8 seconds.
- Retry progress says `Temporary crawler failure; retrying` without resetting
  current or total.
- Exhausted transient failure marks `Wikipedia crawl failed.` and re-raises.
- Permanent completion and programming errors do not retry and mark failure.
- A task misrouted to rebuild or bulk job type never fails that other job.
- Failure-recording errors never replace the original exception.
- `caplog` retains `exc_info` for the original internal failure while the
  durable public error remains exactly `Wikipedia crawl failed.`.
- The Celery app imports `app.workers.wikipedia_tasks`.

- [ ] **Step 2: Run tests and verify missing task registration**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_worker_wikipedia_tasks.py tests/unit/test_celery_config.py -q
```

Expected: collection or import assertions fail for the crawler task.

- [ ] **Step 3: Implement the bound retrying task**

Create `app/workers/wikipedia_tasks.py` with:

```python
TRANSIENT_ERRORS = (
    OperationalError,
    RedisConnectionError,
    RedisTimeoutError,
    WikipediaTransientError,
)


@celery_app.task(
    bind=True,
    name="wikipedia.crawl",
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def wikipedia_crawl_task(task: Task, job_id: str) -> dict[str, Any]:
    if task.request.id is None or task.request.id != job_id:
        raise RuntimeError("Celery task id does not match durable job id.")
    return execute_wikipedia_crawl_attempt(
        task,
        UUID(job_id),
        runner_factory=WikipediaCrawlRunner,
        lock_factory=PostgresAdvisoryLock,
        tracker_factory=JobTracker,
    )
```

Mirror the hardened bulk-task boundary: acquire the job lock, ignore a duplicate
lock owner, retry only `TRANSIENT_ERRORS` while attempts remain, preserve current
progress during retry, log the original exception, and record only the stable
public failure.

Before final failure recording, load the job and require
`job.job_type == WIKIPEDIA_CRAWL_JOB`; return without mutation for missing or
misrouted jobs.

- [ ] **Step 4: Register the task module**

Add `"app.workers.wikipedia_tasks"` to the Celery `imports` tuple and extend the
existing configuration assertion to require it.

- [ ] **Step 5: Run worker and Celery tests**

```bash
/opt/anaconda3/bin/python3 -m pytest tests/unit/test_worker_wikipedia_tasks.py tests/unit/test_celery_config.py tests/unit/test_worker_ingestion_tasks.py tests/unit/test_worker_search_tasks.py -q
```

Expected: all selected worker tests pass.

- [ ] **Step 6: Commit and push**

```bash
git add app/workers/wikipedia_tasks.py app/workers/celery_app.py tests/unit/test_worker_wikipedia_tasks.py tests/unit/test_celery_config.py
git commit -m "feat: execute Wikipedia crawls with Celery"
git push origin main
```

### Task 12: Verify Crawl Persistence With Real PostgreSQL

**Files:**
- Create: `tests/integration/test_wikipedia_crawl_postgres.py`
- Modify: `tests/integration/test_job_repository_postgres.py`

**Interfaces:**
- Verifies: migration constraints, discovery checkpoints, atomic fetch staging, guarded resume, and shared-resource exclusion.
- Consumes: migrated PostgreSQL at revision `20260721_0005`.

- [ ] **Step 1: Write live schema and constraint tests**

Create `tests/integration/test_wikipedia_crawl_postgres.py` with the repository's
existing `RUN_POSTGRES_INTEGRATION=1` marker and savepoint fixture. Add helpers
that create a `wikipedia_crawl` job and run.

Prove the database rejects:

```python
@pytest.mark.parametrize(
    "page_values",
    [
        {"position": -1},
        {"fetch_attempts": -1},
        {"fetch_status": "unknown"},
        {"fetch_status": "fetched", "ingestion_item_id": None},
        {"fetch_status": "failed", "error": None},
    ],
)
def test_database_rejects_invalid_page_state(db_session, page_values): ...
```

Also assert duplicate `(job_id, category_title)`, `(job_id, position)`, and
`(job_id, wikipedia_page_id)` values raise `IntegrityError`.

Add two thread-based race tests using independent `SessionLocal` sessions and a
`threading.Barrier(2)`. For categories, both threads insert the same canonical
title into one committed crawl run. For pages, use different positions but the
same Wikipedia page id. Commit in each thread, collect outcomes through a
thread-safe queue, and assert exactly one commit succeeds and exactly one raises
`IntegrityError` in each race. Delete the committed race fixture in `finally`.

- [ ] **Step 2: Add transactional checkpoint and staging tests**

Use the real `WikipediaCrawlStore` to verify:

- A two-page Action batch stores contiguous positions and its continuation.
- Replaying that same batch does not duplicate pages or categories.
- A second batch resumes and completes discovery.
- Depth and 100-category guards persist exactly.
- A forced exception before checkpoint commit leaves both members and
  continuation unchanged.
- `stage_fetched_page()` creates one ingestion item and fetched transition in one
  commit.
- Repeating fetched staging does not create a second ingestion item.
- `fail_page()` creates one safe terminal error and cannot overwrite fetched.
- `counts()` satisfies all design equations for imported, skipped, ingestion
  failed, and fetch failed siblings.

- [ ] **Step 3: Extend shared-resource conflict coverage**

In `tests/integration/test_job_repository_postgres.py`, create an active crawler
job with `resource_key=SEARCH_INDEX_RESOURCE`, then assert a concurrent active
bulk or rebuild job cannot flush. Repeat with crawler as the second job. Terminal
crawler jobs must release the partial-unique-index slot.

- [ ] **Step 4: Run migration and PostgreSQL tests**

```bash
alembic upgrade head
RUN_POSTGRES_INTEGRATION=1 /opt/anaconda3/bin/python3 -m pytest tests/integration/test_wikipedia_crawl_postgres.py tests/integration/test_job_repository_postgres.py tests/integration/test_bulk_ingestion_postgres.py -q
```

Expected: all selected live PostgreSQL tests pass at revision
`20260721_0005 (head)`.

- [ ] **Step 5: Commit and push**

```bash
git add tests/integration/test_wikipedia_crawl_postgres.py tests/integration/test_job_repository_postgres.py
git commit -m "test: verify Wikipedia crawl persistence"
git push origin main
```

### Task 13: Prove The Complete Crawl-To-Search Flow

**Files:**
- Create: `tests/support/__init__.py`
- Create: `tests/support/fake_wikimedia.py`
- Create: `tests/integration/test_wikipedia_crawl_e2e.py`

**Interfaces:**
- Produces: deterministic local fake Action API and Core REST HTML server.
- Verifies: HTTP submission, Celery runner, retries, item outcomes, PostgreSQL documents, Redis publication, redelivery, and BM25 search.
- Consumes: real local PostgreSQL and Redis plus all crawler production modules.

- [ ] **Step 1: Build the deterministic fake Wikimedia server**

Create `tests/support/fake_wikimedia.py` around
`ThreadingHTTPServer` and `BaseHTTPRequestHandler`. Expose a context manager with
`action_api_url`, `rest_api_url`, request log, and per-title attempt counts.

Serve exactly these category pages:

```python
FIRST_CATEGORY_PAGE = {
    "continue": {"cmcontinue": "page|second", "continue": "-||"},
    "query": {"categorymembers": [
        {"pageid": 101, "ns": 0, "title": "Unique search article"},
        {"pageid": 102, "ns": 0, "title": "Existing search article"},
    ]},
}
SECOND_CATEGORY_PAGE = {
    "batchcomplete": True,
    "query": {"categorymembers": [
        {"pageid": 103, "ns": 0, "title": "Retry search article"},
        {"pageid": 104, "ns": 0, "title": "Missing search article"},
    ]},
}
```

For the unique page's initial REST path, return `302` with a same-host relative
`Location` ending in `?resolved=1`; that resolved request returns valid long
Parsoid HTML. Return valid long HTML directly for the existing page. Return HTTP
`503` plus `Retry-After: 0` once for the retry page, then valid HTML. Always
return `404` for the missing page. Record every `User-Agent`; reject a missing
one in the handler. Add a `python -m tests.support.fake_wikimedia --port 8765`
entry point for separate-process verification.

- [ ] **Step 2: Write the live-services end-to-end test**

Create `tests/integration/test_wikipedia_crawl_e2e.py` with the PostgreSQL marker.
The test must:

1. Start `FakeWikimediaServer`.
2. Override crawler URLs, rate, timeout, and attempts through environment.
3. Insert an existing document with the canonical Existing article URL.
4. Submit a four-article crawl through FastAPI using a real
   `WikipediaCrawlService` and a recording task sender dependency.
5. Execute `wikipedia_crawl_task.apply()` with the returned UUID.
6. Execute the same task id a second time to prove redelivery idempotency.
7. Read the job and page report from PostgreSQL.
8. Load the newly active Redis snapshot into `SearchIndexService`.
9. Search a unique fixture token and assert its imported document ranks.

Assert this exact result shape:

```python
assert result == {
    "root_category": "Category:Featured articles",
    "max_articles": 4,
    "max_depth": 0,
    "categories_visited": 1,
    "category_limit_reached": False,
    "discovered_count": 4,
    "fetched_count": 3,
    "imported_count": 2,
    "duplicate_skipped_count": 1,
    "fetch_failed_count": 1,
    "ingestion_failed_count": 0,
    "failed_count": 1,
    "index_rebuilt": True,
    "index_version": f"redis-{job_id}",
}
```

Assert page positions `[0, 1, 2, 3]`, two imported statuses, one duplicate skip,
one `wikipedia_not_found`, exactly one followed same-host redirect, exactly two
attempts for the transient page, one Redis publication version, and descriptive
user agents on every fake-server request.

Use the existing atomic Lua pointer-restore pattern so cleanup never overwrites
a newer concurrent test snapshot. In a `finally` block, query and retain the ids
of both newly imported documents and the preexisting duplicate fixture before
deleting and committing the job; then delete those documents. Job deletion
cascades crawler and ingestion rows, so document ids must be collected first.

- [ ] **Step 3: Run the deterministic end-to-end test**

```bash
RUN_POSTGRES_INTEGRATION=1 /opt/anaconda3/bin/python3 -m pytest tests/integration/test_wikipedia_crawl_e2e.py -q
```

Expected: the test passes with the exact result above. Assert every recorded
request host equals the running fake server's `127.0.0.1:<port>` authority and
that the complete request log contains only the two configured local API path
prefixes. This makes accidental public-network traffic a test failure.

- [ ] **Step 4: Run end-to-end and regression suites**

```bash
RUN_POSTGRES_INTEGRATION=1 /opt/anaconda3/bin/python3 -m pytest tests/integration/test_wikipedia_crawl_e2e.py tests/integration/test_bulk_ingestion_e2e.py tests/integration/test_search_index_api_postgres.py -q
```

Expected: all crawler, bulk, and search live-service tests pass.

- [ ] **Step 5: Commit and push**

```bash
git add tests/support tests/integration/test_wikipedia_crawl_e2e.py
git commit -m "test: verify Wikipedia crawl end to end"
git push origin main
```

### Task 14: Document, Audit, And Verify The Completed Backend

**Files:**
- Create: `docs/wikipedia-crawler.md`
- Modify: `docs/celery-worker.md`
- Modify: `docs/job-tracking.md`

**Interfaces:**
- Produces: reproducible local operation and troubleshooting instructions.
- Verifies: every acceptance criterion in the approved design and preserves all prior behavior.
- Consumes: complete implementation from Tasks 1 through 13.

- [ ] **Step 1: Write the crawler operations guide**

Create `docs/wikipedia-crawler.md` with exact commands for:

```bash
docker compose up -d postgres redis
alembic upgrade head
celery -A app.workers.celery_app.celery_app worker --loglevel=info
uvicorn app.main:app --reload
```

Document this submission and both inspection calls:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/crawls/wikipedia \
  -H 'Content-Type: application/json' \
  -d '{"category":"Featured articles","max_articles":10,"max_depth":0}'
```

Explain all request bounds, four progress phases, every final count, item error
codes, duplicate-only success, partial success, full-job failure, retention,
canonical URL attribution, user-agent configuration, and the absence of raw HTML
storage. Link the four primary Wikimedia references from the design. Include a
clearly labeled optional live-Wikipedia smoke using at most three articles at
depth zero; state that it is manual evidence and never a CI requirement.

Extend `docs/celery-worker.md` with task name `wikipedia.crawl`, late
acknowledgement, redelivery, and retry behavior. Extend `docs/job-tracking.md`
with crawler ownership of `search_index` and its unknown-to-fixed progress total.

- [ ] **Step 2: Run the complete default suite**

```bash
/opt/anaconda3/bin/python3 -m pytest -q
```

Expected: all non-live tests pass; PostgreSQL-marked tests skip unless explicitly
enabled.

- [ ] **Step 3: Run the complete live PostgreSQL and Redis suite**

```bash
docker compose up -d postgres redis
alembic upgrade head
RUN_POSTGRES_INTEGRATION=1 /opt/anaconda3/bin/python3 -m pytest -q
alembic current
```

Expected: all tests pass and Alembic reports `20260721_0005 (head)`.

- [ ] **Step 4: Verify separate API, worker, broker, and fake-Wikimedia processes**

Run the fake server, worker, and API in three terminals with these shared
environment values:

```bash
WIKIPEDIA_ACTION_API_URL=http://127.0.0.1:8765/w/api.php \
WIKIPEDIA_REST_API_URL=http://127.0.0.1:8765/w/rest.php/v1 \
/opt/anaconda3/bin/python3 -m tests.support.fake_wikimedia --port 8765
```

```bash
WIKIPEDIA_ACTION_API_URL=http://127.0.0.1:8765/w/api.php \
WIKIPEDIA_REST_API_URL=http://127.0.0.1:8765/w/rest.php/v1 \
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

```bash
WIKIPEDIA_ACTION_API_URL=http://127.0.0.1:8765/w/api.php \
WIKIPEDIA_REST_API_URL=http://127.0.0.1:8765/w/rest.php/v1 \
uvicorn app.main:app --port 8000
```

Submit and poll without manual UUID substitution:

```bash
JOB_ID=$(
  curl -sS -X POST http://127.0.0.1:8000/api/v1/crawls/wikipedia \
    -H 'Content-Type: application/json' \
    -d '{"category":"Featured articles","max_articles":4,"max_depth":0}' \
  | /opt/anaconda3/bin/python3 -c \
    'import json, sys; print(json.load(sys.stdin)["job_id"])'
)
STATUS=""
for attempt in $(seq 1 60); do
  JOB_JSON=$(curl -sS "http://127.0.0.1:8000/api/v1/jobs/${JOB_ID}")
  STATUS=$(
    printf '%s' "$JOB_JSON" \
    | /opt/anaconda3/bin/python3 -c \
      'import json, sys; print(json.load(sys.stdin)["status"])'
  )
  printf '%s\n' "$JOB_JSON"
  case "$STATUS" in
    SUCCESS|FAILURE) break ;;
  esac
  sleep 1
done
test "$STATUS" = "SUCCESS"
curl -sS "http://127.0.0.1:8000/api/v1/crawls/wikipedia/${JOB_ID}/items"
curl -sS "http://127.0.0.1:8000/api/v1/search?q=uniquewikipediacrawlterm"
```

Expected: terminal `SUCCESS`, exact 4/3/2/1 crawl counts from Task 13, and one
BM25 result containing `uniquewikipediacrawlterm`. Stop all three foreground
processes before completion.

- [ ] **Step 5: Optionally smoke-test the real Wikipedia boundary**

After the deterministic process check, stop the fake server and restart the
worker and API without `WIKIPEDIA_ACTION_API_URL` or
`WIKIPEDIA_REST_API_URL` overrides. Keep the default descriptive user agent and
submit only this bounded request:

```bash
LIVE_JOB_ID=$(
  curl -sS -X POST http://127.0.0.1:8000/api/v1/crawls/wikipedia \
    -H 'Content-Type: application/json' \
    -d '{"category":"Featured articles","max_articles":3,"max_depth":0}' \
  | /opt/anaconda3/bin/python3 -c \
    'import json, sys; print(json.load(sys.stdin)["job_id"])'
)
LIVE_STATUS=""
for attempt in $(seq 1 120); do
  LIVE_JOB_JSON=$(
    curl -sS "http://127.0.0.1:8000/api/v1/jobs/${LIVE_JOB_ID}"
  )
  LIVE_STATUS=$(
    printf '%s' "$LIVE_JOB_JSON" \
    | /opt/anaconda3/bin/python3 -c \
      'import json, sys; print(json.load(sys.stdin)["status"])'
  )
  printf '%s\n' "$LIVE_JOB_JSON"
  case "$LIVE_STATUS" in
    SUCCESS|FAILURE) break ;;
  esac
  sleep 1
done
test "$LIVE_STATUS" = "SUCCESS"
curl -sS "http://127.0.0.1:8000/api/v1/crawls/wikipedia/${LIVE_JOB_ID}/items"
```

Treat this optional result as manual evidence only; do not gate completion or CI
on this external service check.

- [ ] **Step 6: Audit requirements and repository state**

Run:

```bash
git diff --check
git status --short --branch
UNFINISHED_PATTERN="$(printf '%s%s|%s%s' 'TO' 'DO' 'TB' 'D')"
rg -n "$UNFINISHED_PATTERN" app tests docs/wikipedia-crawler.md
rg -n "print\(" app
```

Expected: no whitespace errors, no unintended generated files, and no crawler
unfinished markers or debugging prints. Review every design acceptance criterion
against a named test or the separate-process smoke result.

- [ ] **Step 7: Commit and push documentation**

```bash
git add docs/wikipedia-crawler.md docs/celery-worker.md docs/job-tracking.md
git commit -m "docs: explain durable Wikipedia crawling"
git push origin main
```

- [ ] **Step 8: Verify the pushed tip**

```bash
git status --short --branch
git rev-parse HEAD origin/main
git log -1 --oneline
```

Expected: the worktree is clean, `HEAD` equals `origin/main`, and the latest
commit is the crawler documentation commit.
