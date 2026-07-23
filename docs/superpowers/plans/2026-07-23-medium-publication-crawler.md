# Plan: Medium Publication Crawler

## Goal

Add a production-shaped, bounded Medium publication crawler to Search Engine 2.0. A user will submit one public Medium publication URL, a maximum article count, and the fixed depth value `0`; the system will discover permitted article URLs through RSS and sitemap metadata, fetch and parse the articles, ingest them through the existing document pipeline, rebuild the shared search index, and expose durable progress and item-level outcomes through the API and the existing Crawls page.

The implementation will preserve the current Wikipedia crawler and its source-specific tables and worker while introducing source-neutral crawl persistence and lifecycle code for Medium. Wikipedia migration into the generic layer is explicitly deferred until the new path is stable.

## Architecture

- `jobs` remains the durable orchestration record and continues to enforce one active index-changing job through `SEARCH_INDEX_RESOURCE`.
- New source-neutral tables `crawl_runs`, `crawl_frontier`, and `crawl_items` store a crawl’s normalized seed, discovery checkpoints, discovered URLs, fetch outcomes, and links to existing `ingestion_items`.
- A `CrawlAdapter` protocol defines `validate_seed`, `discover`, `fetch`, and `parse`. The generic runner owns job claiming, persistence, progress, ingestion, index publication, and terminal error handling.
- `MediumAdapter` owns Medium URL rules, robots policy, RSS/sitemap discovery, canonical URL normalization, Medium HTML extraction, and source-specific request limits.
- The existing `IngestionItemProcessor` remains the single document-ingestion path. Existing duplicate URL behavior is reused so a repeated article is safely skipped rather than creating a second document.
- The existing search-index rebuild and Redis snapshot publication remain the publication step for both crawl types.
- The API adds `/api/v1/crawls/medium` and a source-neutral item report. The existing `/api/v1/crawls/wikipedia` contract remains unchanged.
- The frontend gets one source-aware crawl form and one source-neutral outcome table while preserving the current Wikipedia defaults and tests.

## Tech Stack

- Python 3, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL
- Celery, Redis, `httpx`, `beautifulsoup4`, `lxml`
- React, TypeScript, Vite, Vitest, Testing Library, `lucide-react`
- Existing project service/repository/task patterns and the existing test fixtures

## Global Constraints

- Follow the approved design in `docs/superpowers/specs/2026-07-23-medium-publication-crawler-design.md`.
- Do not remove or rewrite Wikipedia-specific tables, routes, runner, or worker in this feature.
- Only accept HTTPS `medium.com` or `*.medium.com` publication seeds; reject credentials, query strings, fragments, article-only URLs, invalid publication paths, and `max_depth` values other than `0`.
- Respect `robots.txt` for every discovery and article request, identify the crawler with a configured user agent, enforce bounded concurrency, request rate, timeout, retry, response-size, and article-count limits.
- Do not use Medium search, undocumented APIs, archive HTML scraping, or a bypass for robots restrictions.
- Persist safe normalized error codes/messages; do not expose response bodies, authorization data, or raw exception strings in API responses or crawl items.
- Keep payloads in `ingestion_items` private. Item-list responses contain metadata and outcomes only, never article HTML or full content.
- Write tests before implementation for each task. Use saved fixtures and a local fake HTTP server; do not add live Medium network calls to CI.
- After each completed implementation task, run the focused tests, commit the task, and push the commit to `origin main` as requested by the user.

## File Map

Files to add:

- `app/models/crawl.py`
- `app/repositories/crawls.py`
- `app/services/crawl_types.py`
- `app/services/crawl_adapters.py`
- `app/services/crawl_store.py`
- `app/services/crawl_runner.py`
- `app/services/medium_adapter.py`
- `app/services/medium_http.py`
- `app/services/medium_parsing.py`
- `app/schemas/medium_crawls.py`
- `app/services/medium_crawls.py`
- `app/api/v1/medium_crawls.py`
- `app/workers/crawl_tasks.py`
- `alembic/versions/20260723_0006_create_generic_crawls.py`
- `tests/unit/test_crawl_models.py`
- `tests/unit/test_crawl_repository.py`
- `tests/unit/test_crawl_types.py`
- `tests/unit/test_medium_http.py`
- `tests/unit/test_medium_parsing.py`
- `tests/unit/test_medium_adapter.py`
- `tests/unit/test_crawl_runner.py`
- `tests/unit/test_crawl_tasks.py`
- `tests/unit/test_medium_crawl_schemas.py`
- `tests/unit/test_medium_crawls.py`
- `tests/integration/test_medium_crawl_api.py`
- `tests/integration/test_medium_crawl_e2e.py`
- `tests/fixtures/medium/publication-feed.xml`
- `tests/fixtures/medium/publication-sitemap.xml`
- `tests/fixtures/medium/article.html`
- `tests/fixtures/medium/robots.txt`
- `frontend/src/components/CrawlForm.test.tsx`

Files to modify:

- `app/models/job.py`
- `app/models/__init__.py`
- `app/api/dependencies.py`
- `app/api/v1/router.py`
- `app/core/config.py`
- `.env.example`
- `app/workers/celery_app.py`
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/components/WikipediaCrawlForm.tsx`
- `frontend/src/components/CrawlItemsTable.tsx`
- `frontend/src/pages/CrawlsPage.tsx`
- `frontend/src/pages/CrawlsPage.test.tsx`
- frontend crawl styles in the existing stylesheet used by the Crawls page
- relevant project documentation, including `docs/medium-crawler.md`

## Implementation Tasks

### Task 1: Add source-neutral crawl persistence

**Files:** `app/models/crawl.py`, `app/models/job.py`, `app/models/__init__.py`, `app/repositories/crawls.py`, `alembic/versions/20260723_0006_create_generic_crawls.py`, `tests/unit/test_crawl_models.py`, `tests/unit/test_crawl_repository.py`

1. Write model and repository tests first.
   - Assert the `MEDIUM_CRAWL_JOB = "medium_crawl"` constant is available without changing existing job constants.
   - Assert a `CrawlRun` stores `job_id`, `source_key`, `seed_url`, `max_articles`, `max_depth`, `discovery_complete`, and `limit_reached` with the expected defaults.
   - Assert a `CrawlFrontier` stores a stable locator and JSON continuation cursor, and a `CrawlItem` stores position, discovered/canonical URLs, optional source item ID, fetch attempts/status, title, ingestion item ID, and safe error.
   - Assert repository methods create a run, add a frontier checkpoint, add a canonicalized item, list pending items in position order, count discovery/fetch/ingestion outcomes, checkpoint discovery idempotently, and return paginated item views.
   - Assert duplicate `(job_id, canonical_url)` and duplicate `(job_id, position)` are rejected at the persistence boundary.
   - Assert a second delivery of a fetched item does not create a second `IngestionItem` or overwrite a terminal item outcome.

2. Implement `app/models/crawl.py`.
   - Define explicit lowercase status constants for pending, fetched, and failed fetch/frontier outcomes, plus terminal-status tuples.
   - Define `CrawlRun` with a UUID `job_id` foreign key to `jobs.id`, `source_key`, `seed_url`, bounded integer settings, completion flags, and timestamps.
   - Define `CrawlFrontier` with an identity bigint ID, run foreign key, `locator`, `depth`, nullable JSON continuation, status, safe error, and timestamps. Add `(job_id, locator)` uniqueness and status/depth indexes.
   - Define `CrawlItem` with an identity bigint ID, run foreign key, zero-based position, nullable source item ID, discovered URL, canonical URL, nullable title, fetch status, attempts, optional ingestion item foreign key, safe error, fetched timestamp, and timestamps. Add uniqueness for `(job_id, position)`, `(job_id, canonical_url)`, and `ingestion_item_id`, plus checks for non-negative position/attempts and valid status values.
   - Keep the model source-neutral; do not add Medium-specific columns such as author or publication date.

3. Add `MEDIUM_CRAWL_JOB` to `app/models/job.py` and import the new models from `app/models/__init__.py` so Alembic sees them.

4. Implement `app/repositories/crawls.py` around a SQLAlchemy `Session`.
   - Add methods `create_run`, `add_frontier`, `get_run`, `get_run_for_update`, `get_frontier_for_update`, `get_next_pending_frontier`, `add_item`, `get_item_for_update`, `mark_item_fetched`, `mark_item_failed`, `list_pending_item_ids`, `count_item_views`, `counts`, `list_item_views`, and `checkpoint_discovery`.
   - Make `checkpoint_discovery` take a run ID, frontier ID, a bounded batch of `DiscoveredItem` values, and the next continuation. It must lock the run/frontier, deduplicate canonical URLs, stop at `max_articles`, update the frontier status/cursor, and commit atomically with discovered items.
   - Return small dataclasses from repository reads rather than leaking SQLAlchemy model objects into adapters or API code.
   - Sanitize item errors to one line and at most 300 characters at the repository boundary.

5. Create the Alembic revision `20260723_0006_create_generic_crawls.py` after `20260721_0005_create_wikipedia_crawler.py`.
   - Create the three tables with the same PostgreSQL UUID/JSONB/identity conventions used by existing migrations.
   - Add all foreign keys, checks, unique constraints, and indexes from the models.
   - Implement a complete downgrade in reverse dependency order.

6. Run:
   - `pytest tests/unit/test_crawl_models.py tests/unit/test_crawl_repository.py tests/unit/test_wikipedia_crawl_models.py tests/unit/test_wikipedia_crawl_repository.py`
   - the project’s PostgreSQL integration command for the new migration/repository tests
   - `alembic check`

7. Commit and push: `feat: add generic crawl persistence`.

### Task 2: Define the adapter contract and Medium policy primitives

**Files:** `app/services/crawl_types.py`, `app/services/crawl_adapters.py`, `app/services/medium_http.py`, `app/services/medium_parsing.py`, `app/core/config.py`, `.env.example`, `tests/unit/test_crawl_types.py`, `tests/unit/test_medium_http.py`, `tests/unit/test_medium_parsing.py`, `tests/fixtures/medium/article.html`, `tests/fixtures/medium/robots.txt`

1. Write failing unit tests for the shared value objects and Medium primitives.
   - Validate `NormalizedSeed`, `CrawlLimits`, `DiscoveredItem`, `RawPage`, `NormalizedDocument`, `DiscoveryBatch`, and `CrawlCounts` reject blank/control-character values and preserve stable types.
   - Assert Medium user-agent requests carry the configured identifying header.
   - Assert the HTTP wrapper applies timeout and response-byte limits, accepts expected HTML/XML content types, rejects oversized responses, and maps timeout/connection/5xx failures to a transient crawler exception.
   - Assert robots rules are fetched once per host per crawl client, cached in memory, and consulted before an RSS, sitemap, or article request. A disallowed URL must never be requested.
   - Assert the HTML fixture yields the canonical link, title, and cleaned article content while removing scripts, styles, navigation, and empty text.
   - Assert missing canonical URL, missing title, and empty article body become stable parse errors.

2. Implement `app/services/crawl_types.py`.
   - Define immutable dataclasses for the adapter contract.
   - Use `CrawlLimits(max_articles, max_depth, max_response_bytes)` and a `DiscoveryBatch(items, frontier_locator, continuation, complete)` shape so discovery can be checkpointed without exposing database models.
   - Define stable exceptions `CrawlerPolicyError`, `CrawlerTransientError`, `CrawlerPermanentError`, `CrawlerParseError`, and `CrawlerDiscoveryError`; each carries a safe public code.

3. Implement `app/services/crawl_adapters.py`.
   - Define a runtime-checkable `CrawlAdapter` protocol with `validate_seed(seed_url)`, `discover(seed, limits)`, `fetch(discovered_item)`, and `parse(raw_page)`.
   - Define a source registry keyed by `source_key`, with `register_adapter` and `get_adapter` raising a safe unsupported-source error.
   - Keep the registry independent of FastAPI and Celery so the runner can be tested with fake adapters.

4. Implement `app/services/medium_http.py`.
   - Build an async `MediumHttpClient` around `httpx.AsyncClient` with the configured user agent, per-request timeout, bounded response streaming, a small semaphore, and a token/rate limiter.
   - Add a per-client robots cache keyed by origin. Fetch `/robots.txt` before any other host request, parse it with the standard robots parser, and call `can_fetch` using the configured user agent.
   - Implement bounded retries inside the client only for timeout, connection, and HTTP 5xx responses. Use exponential delays capped by settings. Do not retry 4xx, robots denial, invalid content type, oversize, or parse failures.
   - Return `RawPage` with URL, status, content type, and bytes; do not return raw exception text to higher layers.

5. Implement `app/services/medium_parsing.py`.
   - Normalize URLs with lowercase scheme/host, remove fragments, strip known tracking parameters, and preserve the publication path.
   - Parse RSS XML with `lxml`/`ElementTree`, extracting item GUID/link/title and optional publication date only for discovery metadata; do not persist that date in this milestone.
   - Parse sitemap XML and sitemap indexes, honoring the same response and URL limits.
   - Parse article HTML with BeautifulSoup. Prefer the canonical link and `og:title`/document title, then extract the article body from `<article>` or the strongest `<main>` candidate. Remove script/style/nav/aside/form elements and reject empty text.
   - Match discovered canonical URLs to the submitted publication host/path rules and reject article URLs outside that publication.

6. Add settings in `app/core/config.py` and `.env.example` for Medium user agent, concurrency, requests per second, timeout seconds, maximum response bytes, fetch attempts, and discovery retry attempts. Use safe defaults parallel to Wikipedia but independently configurable.

7. Run:
   - `pytest tests/unit/test_crawl_types.py tests/unit/test_medium_http.py tests/unit/test_medium_parsing.py tests/unit/test_config.py`
   - `ruff check app tests` or the repository’s configured Python lint command

8. Commit and push: `feat: add crawl adapter and Medium policy primitives`.

### Task 3: Implement the Medium adapter and generic crawl runner

**Files:** `app/services/medium_adapter.py`, `app/services/crawl_store.py`, `app/services/crawl_runner.py`, `app/workers/crawl_tasks.py`, `app/workers/celery_app.py`, `tests/unit/test_medium_adapter.py`, `tests/unit/test_crawl_runner.py`, `tests/unit/test_crawl_tasks.py`

1. Write adapter tests using the saved RSS, sitemap, robots, and article fixtures.
   - Accept `https://medium.com/towards-data-science` and an allowed Medium subdomain publication URL after canonicalization.
   - Reject HTTP, credentials, query/fragment seeds, `/@author/article`, `/p/article`, missing publication slug, non-Medium hosts, and unsupported depth.
   - Verify RSS is attempted first and its canonical article URLs are yielded in recent-first order.
   - Verify a permitted sitemap is used for archive completion when RSS is insufficient, without fetching archive HTML or using Medium search/API endpoints.
   - Verify RSS/sitemap duplicates collapse by canonical URL, publication-boundary articles are excluded, and discovery stops exactly at `max_articles`.
   - Verify a robots denial prevents the corresponding request and produces a stable policy outcome.
   - Verify transient fetch failures retry within the client and permanent item failures become item-level outcomes.

2. Implement `app/services/medium_adapter.py`.
   - `validate_seed` returns `NormalizedSeed(source_key="medium", canonical_url, origin, publication_path)` and enforces the approved URL contract.
   - `discover(seed, limits)` performs RSS-first discovery, then sitemap discovery only when more items are needed. Yield bounded `DiscoveryBatch` values with frontier locators and continuation metadata for durable checkpoints. Never request archive HTML.
   - `fetch(discovered_item)` uses `MediumHttpClient` to fetch only an allowed canonical article URL.
   - `parse(raw_page)` delegates to Medium HTML parsing and returns `NormalizedDocument(title, canonical_url, content)`.
   - Use the configured request budget and maximum article count; do not let malformed one-off RSS/sitemap records abort valid remaining records unless the discovery source itself is unusable.

3. Implement `app/services/crawl_store.py` as a transaction-safe facade over `CrawlRepository` plus `IngestionItemRepository`.
   - Add `get_run`, `get_counts`, `checkpoint_discovery`, `stage_fetched_document`, `fail_item`, `list_pending_ingestion_ids`, and paginated item-view methods.
   - `stage_fetched_document` must lock the crawl item, create exactly one generic ingestion item at its position, persist title/canonical URL/content, and mark the crawl item fetched in one transaction.
   - Repeated staging or failure after a terminal outcome must be a no-op, making worker redelivery idempotent.
   - Keep fetch errors and ingestion errors distinct in counts and item views.

4. Write generic runner tests with fake tracker, store, adapter, processor, rebuild function, and snapshot store.
   - Assert the runner rejects missing/wrong/terminal jobs safely.
   - Assert it claims a pending `MEDIUM_CRAWL_JOB`, resumes a started run, checkpoints discovery, fetches/parses items, processes pending ingestion IDs, rebuilds the index only when at least one new document was imported, and marks success with source-neutral counts.
   - Assert no usable discovery, no fetched items, and no usable documents produce stable completion errors and no false success.
   - Assert progress totals never move backward and terminal item failures do not stop other items.
   - Assert rerunning a successful job returns its stored result without a second index rebuild.

5. Implement `app/services/crawl_runner.py`.
   - Validate the durable job type and status, claim pending jobs with `JobTracker`, and retrieve the generic run.
   - Resolve the adapter by `source_key`; use one async client/adapter lifecycle for discovery and fetch.
   - Checkpoint every discovery batch, then fetch bounded pending crawl items. For each item, classify policy/permanent/parse failures as item-level and transient infrastructure failures according to the task retry contract.
   - Reuse `IngestionItemProcessor` for staged documents, then reuse `rebuild_search_index_snapshot` and `RedisSearchIndexStore` for publication.
   - Build a result containing source, seed URL, configured limits, discovered/fetched/imported/skipped/fetch-failed/ingestion-failed/total-failed counts, index-rebuilt flag, and index version.

6. Implement `app/workers/crawl_tasks.py`.
   - Register a Celery task named `crawl.medium` with late acknowledgements, worker-lost rejection, and the same task-ID/durable-job-ID check as the Wikipedia task.
   - Wrap `CrawlRunner.run` in the existing PostgreSQL advisory lock and map database/Redis/HTTP transient errors to bounded Celery retries with retry progress.
   - Mark only the matching `MEDIUM_CRAWL_JOB` as failed with the safe message `Medium crawl failed.` after retries are exhausted or a non-retryable runner error escapes.
   - Keep the task dependency-injectable for unit tests.

7. Add `app.workers.crawl_tasks` to the Celery import tuple in `app/workers/celery_app.py` without removing existing task modules.

8. Run:
   - `pytest tests/unit/test_medium_adapter.py tests/unit/test_crawl_runner.py tests/unit/test_crawl_tasks.py tests/unit/test_wikipedia_crawl_runner.py tests/unit/test_wikipedia_crawl_tasks.py`
   - the full Python unit suite

9. Commit and push: `feat: run Medium crawls through generic workers`.

### Task 4: Add the Medium API contract and service

**Files:** `app/schemas/medium_crawls.py`, `app/services/medium_crawls.py`, `app/api/v1/medium_crawls.py`, `app/api/dependencies.py`, `app/api/v1/router.py`, `tests/unit/test_medium_crawl_schemas.py`, `tests/unit/test_medium_crawls.py`, `tests/integration/test_medium_crawl_api.py`

1. Write schema tests before implementation.
   - Accept the default `max_articles=100` and `max_depth=0`.
   - Accept a canonical publication URL with or without a trailing slash and normalize it to an origin plus publication path.
   - Reject HTTP, non-Medium hosts, article-only paths, credentials, query/fragment components, blank/control-character URLs, `max_articles` outside `1..500`, `bool` values, nonzero depth, and unknown fields.
   - Assert item-list schemas expose position, source item ID, title, URL, fetch status, ingestion status, document ID, and error while excluding content/HTML.

2. Implement `MediumCrawlRequest` and source-neutral item/list response models in `app/schemas/medium_crawls.py`.
   - Use strict Pydantic configuration with `extra="forbid"` and validated defaults.
   - Keep URL normalization in one shared function used by the adapter and request validator so API and worker behavior cannot drift.
   - Use `CrawlItemResponse`/`CrawlItemListResponse` for item reporting; retain the existing Wikipedia response models for backward compatibility.

3. Write service tests with fake job/crawl repositories and task senders.
   - Assert enqueue creates a pending job with `MEDIUM_CRAWL_JOB`, `SEARCH_INDEX_RESOURCE`, and the correct progress message, then creates a generic run and initial RSS/sitemap frontier state before committing.
   - Assert the task is sent with the durable job ID as both argument and Celery task ID.
   - Assert an active index job maps to `IndexJobConflictError` and no second run is created.
   - Assert storage and enqueue failures roll back state and map to the existing safe service errors.
   - Assert item listing rejects unknown or wrong-type jobs and returns stable pagination.

4. Implement `app/services/medium_crawls.py` using the existing `JobRepository`, generic `CrawlRepository`, and `TaskSender` patterns.
   - Keep enqueue and item-list operations synchronous and transaction-scoped like the Wikipedia service.
   - Use `celery_app.signature("crawl.medium")` from a new dependency provider.
   - Preserve the existing active-index conflict contract and `/api/v1/jobs/{job_id}` status URL.

5. Implement `app/api/v1/medium_crawls.py`.
   - `POST /api/v1/crawls/medium` returns `202` and `JobAcceptedResponse`.
   - `GET /api/v1/crawls/medium/{job_id}/items?limit=100&offset=0` returns paginated source-neutral outcomes.
   - Map validation to FastAPI `422`, active index conflict to `409`, unknown/wrong job to `404`, and storage/enqueue failures to `503` with safe details.
   - Keep item-list bounds identical to Wikipedia: `limit 1..100`, `offset >= 0`.

6. Register the dependency and router in `app/api/dependencies.py` and `app/api/v1/router.py`. Do not change the existing Wikipedia route registration.

7. Run:
   - `pytest tests/unit/test_medium_crawl_schemas.py tests/unit/test_medium_crawls.py tests/integration/test_medium_crawl_api.py tests/integration/test_wikipedia_crawl_api.py`
   - `pytest` for the full Python suite

8. Commit and push: `feat: expose Medium crawl API`.

### Task 5: Make the Crawls page source-aware

**Files:** `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/components/WikipediaCrawlForm.tsx`, `frontend/src/components/CrawlItemsTable.tsx`, `frontend/src/pages/CrawlsPage.tsx`, `frontend/src/pages/CrawlsPage.test.tsx`, `frontend/src/components/CrawlForm.test.tsx`, the existing frontend crawl stylesheet

1. Write frontend tests first.
   - Preserve the current Wikipedia validation, submission payload, polling, duplicate-job error, terminal failure, and item outcome assertions.
   - Add a source selector with Wikipedia selected by default.
   - Selecting Medium replaces category/depth inputs with publication URL and a disabled/read-only depth value of `0`, keeps the article limit bound `1..500`, and shows source-specific validation.
   - Submitting Medium calls the Medium endpoint with `{ publication_url, max_articles, max_depth: 0 }` and does not call the Wikipedia client.
   - A Medium terminal job calls `listMediumCrawlItems` and renders the same progress/outcome table without a Wikipedia page ID label.
   - Restoring a stored Medium job uses the job’s `job_type` to select the Medium item endpoint; restoring a Wikipedia job continues to use the existing endpoint.
   - Assert source labels and form fields remain accessible by label, and no long URL or status text overflows the existing responsive layout.

2. Extend `frontend/src/api/types.ts`.
   - Add `CrawlSource`, `CrawlFormValues`, `CrawlItem`, and `CrawlItemListResponse` types.
   - Keep `WikipediaCrawlItem` aliases/types where current tests and other pages rely on them, or make the existing type a compatible specialization with `source_item_id` mapped from `wikipedia_page_id` at the API boundary.
   - Add `MediumCrawlItemListResponse` only if it improves type clarity; the page should consume the source-neutral item type.

3. Extend `frontend/src/api/client.ts` with `submitMediumCrawl` and `listMediumCrawlItems` using the existing JSON/error helper and exact API paths. Keep all existing Wikipedia functions unchanged.

4. Evolve `frontend/src/components/WikipediaCrawlForm.tsx` into a backward-compatible source-aware form.
   - Export `CrawlForm` and retain a `WikipediaCrawlForm` compatibility export if existing imports/tests require it.
   - Use a source selector with the two supported sources. Keep the current Wikipedia defaults and field names.
   - For Medium, validate HTTPS host/path shape in the client for fast feedback but keep the server as the authority. Force depth to `0` in the submitted discriminated union.
   - Keep the submit button icon, loading state, inline errors, and existing keyboard/ARIA behavior.

5. Update `frontend/src/components/CrawlItemsTable.tsx` to accept `CrawlItem[]`.
   - Render a source-neutral “Source item” line only when `source_item_id` exists.
   - Keep external article links, fetch/index/document status badges, safe errors, position ordering, and responsive labels.
   - Use a source-neutral table label and state copy.

6. Update `frontend/src/pages/CrawlsPage.tsx`.
   - Track the selected source for a new submission and infer source from `job.job_type` when a stored job is restored.
   - Dispatch to Wikipedia or Medium submit/list functions through small typed helpers, then keep one shared polling/progress/item-display flow.
   - Change copy from Wikipedia-only to source-aware copy while preserving the existing bounded-pipeline explanation and active-job preference behavior.
   - Clear stale item/error state when switching source or starting a new crawl.

7. Run:
   - `cd frontend && npm test -- --run src/pages/CrawlsPage.test.tsx src/components/CrawlForm.test.tsx`
   - `cd frontend && npm run build`
   - `cd frontend && npm run lint`

8. Commit and push: `feat: add source-aware crawl controls`.

### Task 6: Add local end-to-end coverage and documentation

**Files:** `tests/integration/test_medium_crawl_e2e.py`, `docs/medium-crawler.md`, the project README/development documentation where crawl commands are documented, `tests/fixtures/medium/*` as needed

1. Build a deterministic local fake Medium server in `tests/integration/test_medium_crawl_e2e.py`.
   - Serve `/robots.txt`, the publication RSS feed, a sitemap, and two article HTML pages.
   - Record requested paths and user-agent headers.
   - Include one duplicate RSS/sitemap URL, one malformed/non-publication record, and one retryable article response so the test exercises deduplication and retry behavior.
   - Configure the adapter test settings to point at the local server only through test dependency injection; do not weaken production Medium host validation.

2. Assert the complete flow using real database/repository code and fake Celery dispatch where the project’s integration harness requires it:
   - submit a publication crawl;
   - run the worker task synchronously;
   - observe job success, progress/result counts, and one search-index publication;
   - verify documents are searchable by title/body;
   - verify the item endpoint exposes imported and failed outcomes but no content/HTML;
   - rerun the same publication as a new job and verify document URL uniqueness causes safe duplicate skips;
   - verify request logs contain robots before content and no forbidden archive/search/API request.

3. Add `docs/medium-crawler.md` covering:
   - the publication-scoped request contract and example curl commands;
   - RSS-first/sitemap fallback discovery;
   - robots, rate, timeout, retry, response-size, and article-count limits;
   - job status and item outcome endpoints;
   - how the generic adapter boundary differs from the preserved Wikipedia implementation;
   - local fixture/e2e test commands;
   - explicit non-goals and the future path for migrating Wikipedia.

4. Run the complete verification set:
   - `pytest`
   - `cd frontend && npm test -- --run`
   - `cd frontend && npm run build`
   - `cd frontend && npm run lint`
   - `alembic check`
   - the repository’s PostgreSQL migration/integration command

5. Inspect the final diff for accidental Wikipedia regressions, raw HTML in API responses, unsafe exception leakage, unbounded network behavior, and frontend overflow at desktop and mobile widths.

6. Commit and push: `test: cover Medium crawler end to end`, followed by a final `git status --short` and remote verification of `main`.

## Completion Criteria

- A valid Medium publication submission returns `202`, creates a durable generic crawl run, and is processed by the Celery worker.
- RSS discovery is attempted first, permitted sitemap discovery can fill the bounded limit, and canonical duplicates/out-of-publication links are excluded.
- Robots, concurrency, rate, timeout, retry, and response-size policies are enforced by tests.
- Fetched articles pass through the existing ingestion processor and appear in the shared search index.
- The job status endpoint and Medium item endpoint report durable progress and safe per-item outcomes.
- The frontend can start and monitor both Wikipedia and Medium crawls without breaking the existing Wikipedia behavior.
- Duplicate delivery and repeated publication crawls do not create duplicate documents or duplicate ingestion items.
- All focused and full test/build/lint/migration checks pass, and each task has been committed and pushed to `main`.
