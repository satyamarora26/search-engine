# Wikipedia Category Crawler

The crawler imports a bounded English Wikipedia category into the existing
PostgreSQL document store and BM25 search snapshot. PostgreSQL owns the durable
job, category frontier, discovered pages, fetch outcomes, and ingestion outcomes.
Redis carries the Celery task and publishes the versioned search snapshot.

## Start The Stack

```bash
docker compose up -d postgres redis
alembic upgrade head
celery -A app.workers.celery_app.celery_app worker --loglevel=info
uvicorn app.main:app --reload
```

Run the worker and API commands in separate terminals.

## Submit And Inspect

```bash
curl -X POST http://127.0.0.1:8000/api/v1/crawls/wikipedia \
  -H 'Content-Type: application/json' \
  -d '{"category":"Featured articles","max_articles":10,"max_depth":0}'
```

The endpoint returns `202 Accepted` with a durable `job_id` and `status_url`.
Use the returned UUID in both inspection calls:

```bash
curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID
curl http://127.0.0.1:8000/api/v1/crawls/wikipedia/JOB_ID/items
```

The item report is ordered by discovery position and is paginated with
`limit=1..100` and `offset>=0`. It contains the page id, title, canonical URL,
fetch status, ingestion status, document id when imported, and a safe error. It
never returns raw HTML or the full article payload.

## Request Bounds

- `category` defaults to `Featured articles`, is stored with one
  `Category:` prefix, and must be a nonblank title of at most 255 characters.
- `max_articles` defaults to 100 and accepts 1 through 500.
- `max_depth` defaults to 0 and accepts 0 through 2.
- Wikimedia hosts and API paths come from configuration, not the request body.

The worker uses the configured concurrency, requests-per-second rate, timeout,
maximum response size, retry attempts, and descriptive user agent. The default
user agent identifies this project:

```text
SatyamSearchEngineBot/1.0 (https://github.com/satyamarora26/search-engine)
```

Override these values with `WIKIPEDIA_*` environment variables when running the
API and worker. Keep the same endpoint configuration in both processes.

## Worker Phases

Each crawl advances through four durable phases:

1. **Discovery** walks category members breadth-first and checkpoints Action API
   continuation state in PostgreSQL.
2. **Fetch** retrieves rendered Parsoid HTML with bounded asynchronous requests,
   follows same-host redirects, and records retries and terminal failures.
3. **Ingestion** extracts searchable prose and sends each staged payload through
   the existing document-ingestion processor.
4. **Publication** rebuilds BM25 once when at least one document changed, writes
   the complete Redis snapshot, and then updates the active version pointer.

After discovering `N` pages, job progress has total `N + 1`: one unit per
terminal page outcome and one final publication unit. While discovery is still
running, the total is unknown.

## Outcomes And Results

The final result contains:

`root_category`, `max_articles`, `max_depth`, `categories_visited`,
`category_limit_reached`, `discovered_count`, `fetched_count`,
`imported_count`, `duplicate_skipped_count`, `fetch_failed_count`,
`ingestion_failed_count`, `failed_count`, `index_rebuilt`, and `index_version`.

Typical page errors include `wikipedia_not_found`,
`wikipedia_request_failed`, `wikipedia_request_rejected`,
`wikipedia_redirect_rejected`, `wikipedia_invalid_response`,
`wikipedia_invalid_content_type`, `wikipedia_response_too_large`,
`missing_article_body`, `empty_article_content`, and
`content_too_short`. Ingestion can report `duplicate_url`, validation errors,
or a safe document-integrity error.

A crawl is successful when it produces at least one usable document: imported
pages or pages skipped because their canonical URL already exists. A
duplicate-only crawl succeeds without rebuilding the index and keeps the active
snapshot version. A crawl with no fetched articles or no usable documents fails
with a safe job error. Partial success is represented by `SUCCESS` plus the
per-page and aggregate failure counts.

Canonical URLs use the stable Wikipedia article form, such as
`https://en.wikipedia.org/wiki/Featured_article`. The crawler stores this URL
for attribution and duplicate detection; it does not store raw HTML.

Version 1 retains job rows, staged ingestion payloads, outcomes, documents, and
Redis snapshots indefinitely. Automatic retention and snapshot pruning are
future operational work.

## Deterministic Local Verification

The end-to-end test uses a local fake Wikimedia boundary and never depends on
public Wikipedia. It exercises Action API pagination, a same-host redirect, a
transient `503` retry, a permanent `404`, PostgreSQL persistence, Redis
publication, Celery redelivery, and BM25 search.

Run the automated check after starting PostgreSQL and Redis:

```bash
RUN_POSTGRES_INTEGRATION=1 /opt/anaconda3/bin/python3 -m pytest \
  tests/integration/test_wikipedia_crawl_e2e.py -q
```

For a separate-process check, start the fake server, worker, and API in three
terminals. The worker and API must share the local Wikimedia endpoint values:

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

Submit and poll the deterministic four-page crawl:

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

The expected deterministic counts are 4 discovered, 3 fetched, 2 imported, 1
duplicate skipped, and 1 fetch failure. Stop all foreground processes after the
check.

## Optional Live Smoke

As manual evidence only, the endpoint can be tested against real Wikipedia with
at most three articles and depth zero:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/crawls/wikipedia \
  -H 'Content-Type: application/json' \
  -d '{"category":"Featured articles","max_articles":3,"max_depth":0}'
```

This external-service check is never a CI requirement. Keep the default
descriptive user agent, respect Wikimedia rate guidance, and inspect the job and
item endpoints rather than storing or printing article HTML.

## Primary Wikimedia References

- [MediaWiki Categorymembers API](https://www.mediawiki.org/wiki/API:Categorymembers)
- [MediaWiki Core REST page endpoint migration](https://www.mediawiki.org/wiki/RESTBase/service_migration)
- [Wikimedia API Usage Guidelines](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines)
- [Wikimedia User-Agent Policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)
