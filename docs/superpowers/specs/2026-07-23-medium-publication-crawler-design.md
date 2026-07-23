# Medium Publication Crawler Design

## Status

Approved design pending written-spec review.

## Goal

Add a bounded, compliant crawler for one public Medium publication at a time,
using the existing Celery jobs, document-ingestion service, PostgreSQL source of
truth, Redis search snapshots, and frontend crawl monitor.

The crawler will make public Medium articles searchable in the same product as
Wikipedia articles. It will also establish a reusable source-adapter boundary
for future sources without forcing a risky rewrite of the working Wikipedia
crawler in this milestone.

## Product Scope

The first version accepts a public Medium publication URL, discovers a bounded
set of public article URLs, fetches and parses those articles, and imports them
through the existing ingestion pipeline.

Example request:

```text
POST /api/v1/crawls/medium
{
  "publication_url": "https://medium.com/towards-data-science",
  "max_articles": 50,
  "max_depth": 0
}
```

`max_articles` is bounded from 1 through 500. Medium publication discovery does
not follow article links in this version, so `max_depth` defaults to and only
accepts `0`. The field remains in the shared crawl contract for sources that
need bounded traversal later.

The crawler only handles public HTTPS publication pages and public article
pages. It does not authenticate, bypass paywalls, defeat access controls, or
pretend that restricted content is public.

## Architecture Decision

Introduce a generic crawler runner and source-adapter contract while retaining
the existing Wikipedia-specific runner and tables for compatibility. Medium
will be the first source to use the new generic persistence path. A later
milestone may migrate Wikipedia onto the generic tables after the shared
contract has been proven.

```text
FastAPI medium route
        |
        v
Generic crawl service + PostgreSQL job/run/item rows
        |
        v
Celery generic crawl runner
        |
        v
Medium adapter
  discovery -> fetch -> parse
        |
        v
Existing document ingestion service
        |
        v
Search-index rebuild and versioned snapshot publication
```

The generic runner owns lifecycle and reliability behavior. Adapters own only
source-specific URL validation, discovery, HTTP response interpretation, and
content parsing.

## Discovery Strategy

Medium discovery is hybrid but bounded:

1. Validate and normalize the publication seed URL.
2. Use an available public publication RSS feed as the recent-first source.
3. Use permitted sitemap entries as the archive source when available.
4. Combine discovered URLs, canonicalize them, remove duplicates, and stop at
   `max_articles`.
5. Keep only public article URLs that belong to the requested publication or
   resolve to its canonical publication identity.

The adapter does not crawl Medium search pages or depend on undocumented
internal JSON APIs. It does not use publication archive HTML as the primary
discovery mechanism in version 1 because that creates a brittle dependency on
page layout and client-side rendering.

If neither permitted RSS nor sitemap discovery yields a usable bounded set,
the crawl records a safe discovery failure rather than broadening into an
unbounded site crawl.

## Source Adapter Contract

The generic runner uses a source adapter registry keyed by `source_key`.
Medium is registered as `medium`.

Conceptually, each adapter supplies:

```text
validate_seed(seed_url) -> NormalizedSeed
discover(seed, limits) -> iterable[DiscoveredItem]
fetch(discovered_item) -> RawPage
parse(raw_page) -> NormalizedDocument
```

`NormalizedDocument` contains only the fields needed by the current document
pipeline:

```text
title: str
canonical_url: str
content: str
```

The existing `Document.created_at` remains the ingestion timestamp. Medium's
article publication date and author are not persisted in this milestone, so
they cannot be confused with the date used by the current search metadata
filter.

## Generic Persistence

The existing `jobs` table remains the lifecycle source of truth and keeps the
same public job ID used by Celery and the job-status API.

Add source-neutral crawl records:

### `crawl_runs`

- `job_id`: primary key and foreign key to `jobs.id`;
- `source_key`: `medium` for this milestone;
- `seed_url`: normalized publication URL;
- `max_articles`: bounded article limit;
- `max_depth`: zero for Medium;
- discovery completion and limit flags;
- created and updated timestamps.

### `crawl_frontier`

- `job_id` and frontier identity;
- source-specific locator or URL;
- traversal depth;
- continuation/checkpoint JSON when a feed or sitemap is paginated;
- pending, completed, or failed status;
- safe error text.

### `crawl_items`

- `job_id` and stable position;
- discovered URL and canonical URL;
- optional source item identifier;
- title when discovery provides it;
- fetch status and attempt count;
- staged ingestion item ID;
- fetched timestamp and safe item error.

The existing Wikipedia-specific tables are not removed or migrated as part of
this feature. Generic Medium rows must not be written into Wikipedia-only
tables. Existing document URL uniqueness and the ingestion service remain the
deduplication and import boundaries.

## Fetching and Parsing

The Medium adapter uses the existing project's asynchronous HTTP patterns and
adds a clearly identifying User-Agent. It checks robots policy before fetching
discovery resources and article pages, applies bounded concurrency, and enforces
request timeout and response-size limits.

For a public article response, parsing uses structured and semantic HTML in
this order:

1. canonical URL from the canonical link or equivalent metadata;
2. title from article metadata, document title, or the article heading;
3. body text from the article content container, excluding scripts, styles,
   navigation, subscription prompts, and unrelated page chrome.

The parser rejects an article when it cannot produce a canonical URL, title, or
non-empty searchable body. It returns a normalized URL without query and
fragment components for deduplication while preserving the canonical public
article URL for the document record.

## Reliability and Error Handling

- Validate only public HTTPS Medium publication URLs.
- Cache robots policy per host for the duration of a crawl and deny fetches
  disallowed for this crawler's User-Agent.
- Retry timeouts, connection failures, and HTTP 5xx responses with bounded
  exponential backoff.
- Treat HTTP 4xx responses, robots denial, invalid HTML, and empty article
  content as item-level failures unless discovery itself cannot continue.
- Cap attempts, response bytes, concurrency, and total article count.
- Persist safe, normalized error messages; never store response bodies or
  credentials in job errors.
- Make item staging and final ingestion idempotent across Celery redelivery.
- Treat an article that already exists by canonical URL as a safe duplicate
  outcome, not a crawl failure.
- A crawl succeeds when it discovers usable items and finishes its bounded
  pipeline, even if some individual items fail or are duplicates.
- A crawl fails when seed validation, discovery, or the complete bounded run
  cannot produce a usable outcome.
- The existing shared `search_index` resource lock prevents a Medium crawl from
  publishing concurrently with bulk ingestion, Wikipedia crawling, or index
  rebuilds.

Medium publishes a sitemap and its robots policy restricts selected paths, so
the crawler must follow the site policy and must not use restricted paths as a
workaround. The Medium API documentation is archived and states that the API is
no longer supported; this design therefore uses permitted public discovery and
HTML fetching rather than an API integration.

## API Contract

Add:

```text
POST /api/v1/crawls/medium
GET  /api/v1/crawls/medium/{job_id}/items?limit=100&offset=0
```

The submit response reuses `JobAcceptedResponse`. The job can be monitored by
the existing:

```text
GET /api/v1/jobs/{job_id}
```

Request validation includes:

- only HTTPS URLs;
- a host of `medium.com` or a `*.medium.com` publication subdomain;
- no credentials, query strings, fragments, or article-only URL as the
  publication seed;
- `max_articles` from 1 through 500;
- `max_depth` equal to 0.

Invalid input returns HTTP 422. An active index-changing job returns the same
HTTP 409 conflict shape as the existing Wikipedia and bulk-ingestion routes.
Unknown Medium job IDs return HTTP 404, storage failures return HTTP 503, and
accepted jobs return HTTP 202.

The item list returns source-neutral item fields: position, title, canonical
URL, fetch status, ingestion status, document ID, and safe error.

## Frontend Behavior

The current crawl page becomes source-aware without introducing a second
monitoring page.

- Add a source selector with `Wikipedia` and `Medium` options.
- Preserve the existing Wikipedia category form unchanged in behavior.
- Show a Medium publication URL field and article-limit field for Medium.
- Keep the shared submit, accepted-job, polling, progress, retry, and item
  outcome components.
- Display Medium item outcomes using title, canonical URL, fetch status,
  ingestion status, and document ID.
- Continue storing the active job ID in the existing browser preference so a
  refresh reconnects to either source.
- Keep the current `source=medium.com` search filter usable automatically for
  imported Medium URLs.

The first UI does not include author search, publication-date filtering,
authentication, private article access, paywall bypassing, or a standalone
Medium search interface.

## Testing Contract

Backend unit tests cover:

1. publication URL validation and normalization;
2. canonical URL deduplication and publication matching;
3. sitemap/RSS discovery limits and pagination checkpoints;
4. HTML parsing from deterministic saved fixtures;
5. robots denial, retryable failures, permanent failures, response-size
   limits, and empty-content rejection;
6. generic runner progress, duplicate outcomes, item failures, and idempotent
   redelivery;
7. generic repository/model constraints and safe error persistence.

API tests cover:

1. accepted Medium crawl requests;
2. validation failures and HTTP status codes;
3. active index-job conflicts;
4. job status and paginated item listing;
5. storage and enqueue failure behavior.

Frontend tests cover:

1. switching between Wikipedia and Medium forms;
2. Medium URL and article-limit validation;
3. submit request serialization;
4. job polling and terminal state handling;
5. Medium item rendering and error states;
6. reconnection after refresh.

An end-to-end test uses a local fake Medium server with deterministic RSS,
sitemap, robots, and article responses. It verifies that a bounded crawl
creates a job, imports a searchable document, handles duplicate canonical URLs
and item failures, and publishes a new index snapshot. CI must not make live
requests to Medium.

## Non-Goals

- Crawling all of Medium or using Medium search for discovery.
- Supporting arbitrary custom publication domains in version 1.
- Bypassing robots policy, authentication, paywalls, or access controls.
- Relying on the unsupported Medium API.
- Persisting author or publication-date fields.
- Adding semantic, vector, or recommendation ranking.
- Migrating the existing Wikipedia tables in this milestone.
- Building a general-purpose web crawler for arbitrary domains.

## Success Criteria

The feature is complete when a user can submit a bounded public Medium
publication crawl, monitor the same job lifecycle used by Wikipedia, inspect
source-neutral item outcomes, search an imported article through the existing
BM25/TF-IDF engine, rerun safely without duplicate documents, and pass all
deterministic backend/frontend tests without live Medium network access.
