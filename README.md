# SearchEngine

SearchEngine is a production-style lexical search platform built from scratch
for learning and placement preparation. It turns documents from APIs, crawlers,
or direct uploads into a searchable library and exposes both a REST API and a
React workspace for searching, indexing, and inspecting background jobs.

The project focuses on the engineering behind search rather than only calling a
hosted search service: text analysis, inverted indexes, BM25 ranking, TF-IDF
comparison, durable ingestion, asynchronous workers, versioned snapshots,
metadata filters, and reproducible performance tests.

[![CI](https://github.com/satyamarora26/search-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/satyamarora26/search-engine/actions/workflows/ci.yml)

## What It Can Do

- Search indexed documents with BM25 by default, with TF-IDF available as a
  baseline for comparison.
- Search all text, title only, or content only; paginate results; match exact
  phrases; and filter by source hostname or ingestion date.
- Explain a BM25 result by showing term frequency, document frequency, IDF, and
  each term's score contribution.
- Store active documents and durable job history in PostgreSQL.
- Process bulk uploads and crawls asynchronously through Celery and Redis so
  long-running work does not block FastAPI requests.
- Crawl bounded content from Wikipedia categories, Medium publications, and
  public RSS/Atom feeds.
- Publish versioned document snapshots through Redis and let each API process
  rebuild and atomically activate its own in-memory search index.
- Monitor crawl phases, item-level outcomes, progress, failures, and index
  publication from the React frontend.

## Why This Architecture

This project is intentionally split into clear responsibilities:

```text
                         +----------------------+
                         | React + TypeScript UI |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | FastAPI REST API      |
                         +----+-------------+---+
                              |             |
                    documents |             | search
                              v             v
                    +---------+--+   +------+----------------+
                    | PostgreSQL |   | Process-local engine  |
                    | source of  |   | BM25 / TF-IDF          |
                    | truth      |   +------+----------------+
                    +------+-----+          ^
                           |                 |
                 jobs/items |          versioned snapshot
                           v                 |
                    +------+-----+     +-----+------+
                    | Redis      +<----+ Celery     |
                    | broker,    |     | workers    |
                    | results,   |     +-----+------+
                    | snapshots  |           |
                    +------------+           v
                                      crawlers / ingestion
```

### Request and indexing flow

1. A client submits a document batch or crawl request to FastAPI.
2. FastAPI validates the request, creates a durable PostgreSQL job, and returns
   `202 Accepted` with a job UUID.
3. The UUID is sent through Redis to a Celery worker. PostgreSQL remains the
   source of truth for job state, progress, item outcomes, and documents.
4. The worker processes items independently, records partial failures safely,
   and rebuilds the search index once after successful document changes.
5. The worker writes a complete versioned Redis snapshot before moving the
   active-version pointer. API processes detect the new version, rebuild a
   replacement engine, and swap it in atomically.

This gives the project a useful process boundary: Celery does not reach into
FastAPI memory, and Redis does not replace PostgreSQL as the durable database.

## Search Internals

The search pipeline is deliberately understandable and testable:

```text
raw title/content
      -> analyzer and token normalization
      -> inverted index with postings and term frequencies
      -> candidate matching
      -> BM25 or TF-IDF scoring
      -> filters, exact-phrase checks, pagination, snippets
```

BM25 is the default ranker because it handles document length and term
frequency saturation more robustly than plain TF-IDF for varied document sizes.
TF-IDF remains available as a transparent baseline for ranking evaluation.

The optimized query path avoids scoring every document when the query has a
small candidate set, caches average document length for BM25, streams postings,
and selects the requested top-k results without sorting every match.

## Technology Stack

| Layer | Technology | Role |
| --- | --- | --- |
| API | Python, FastAPI, Pydantic | Typed HTTP contracts and interactive API docs |
| Retrieval | Custom Python inverted index, BM25, TF-IDF | Token matching and lexical ranking |
| Persistence | PostgreSQL, SQLAlchemy, Alembic | Documents, jobs, crawl state, and migrations |
| Background work | Celery | Asynchronous indexing, ingestion, and crawling |
| Queue and snapshots | Redis | Celery broker/result backend and versioned index payloads |
| Crawling | HTTPX, BeautifulSoup, lxml | Bounded fetching and content extraction |
| Frontend | React, TypeScript, Vite, lucide-react | Search workspace, crawl monitoring, and document library |
| Local infrastructure | Docker Compose | Reproducible PostgreSQL and Redis services |
| Quality | Pytest, Vitest, Oxlint, GitHub Actions | Backend tests, frontend checks, and CI |

## Quickstart

### Prerequisites

- Python 3.12 or newer
- Node.js 22 or newer
- Docker Desktop with Docker Compose

### 1. Clone and install backend dependencies

```bash
git clone https://github.com/satyamarora26/search-engine.git
cd search-engine

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

The application defaults match the local Docker Compose services. To customize
them, copy `.env.example`, export the values in your shell, and then start the
services:

```bash
cp .env.example .env
set -a && source .env && set +a
```

### 2. Start PostgreSQL and Redis

```bash
docker compose up -d postgres redis
alembic upgrade head
docker compose ps
```

### 3. Start the Celery worker and API

Run each command in a separate terminal from the repository root, with the
virtual environment active:

```bash
celery -A app.workers.celery_app.celery_app worker --loglevel=info
```

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at `http://127.0.0.1:8000`.

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- Health: `http://127.0.0.1:8000/api/v1/health`

### 4. Start the frontend

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development server proxies `/api`
requests to the FastAPI service at port `8000`.

## Try the API

### Add a document and search it

```bash
curl -X POST http://127.0.0.1:8000/api/v1/documents \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Understanding BM25",
    "content": "BM25 ranks documents using term frequency, document frequency, and document length.",
    "url": "https://example.com/bm25"
  }'

curl 'http://127.0.0.1:8000/api/v1/search?q=document+ranking&ranking=bm25&limit=10'
```

### Search with product-facing controls

```bash
curl 'http://127.0.0.1:8000/api/v1/search?q=search+engine&scope=content&exact_phrase=true&limit=10'
curl 'http://127.0.0.1:8000/api/v1/search?q=python&source=wikipedia.org'
curl 'http://127.0.0.1:8000/api/v1/search?q=python&created_from=2026-07-01&created_to=2026-07-31'
```

Every result includes its title, URL, score, snippet, matched terms, and the
active index version. The response also reports the server-applied filters and
the total number of matching documents.

### Explain a result

Use a returned `document_id` to inspect why a BM25 result received its score:

```bash
curl 'http://127.0.0.1:8000/api/v1/search/explain?q=bm25&document_id=1'
```

### Submit bulk ingestion

Bulk ingestion returns immediately with a durable job ID. Items may finish as
`imported`, `skipped`, or `failed` independently:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/documents/bulk \
  -H 'Content-Type: application/json' \
  -d '{
    "documents": [
      {"title":"BM25", "content":"BM25 ranking", "url":"https://example.com/bm25-bulk"},
      {"title":"TF-IDF", "content":"TF-IDF baseline", "url":"https://example.com/tfidf-bulk"}
    ]
  }'

curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID
curl 'http://127.0.0.1:8000/api/v1/documents/bulk/JOB_ID/items?limit=100&offset=0'
```

### Crawl content sources

Wikipedia category crawl:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/crawls/wikipedia \
  -H 'Content-Type: application/json' \
  -d '{"category":"Featured articles","max_articles":10,"max_depth":0}'
```

Medium publication crawl:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/crawls/medium \
  -H 'Content-Type: application/json' \
  -d '{"publication_url":"https://medium.com/towards-data-science","max_articles":10}'
```

RSS or Atom feed crawl:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/crawls/rss \
  -H 'Content-Type: application/json' \
  -d '{"feed_url":"https://hnrss.org/frontpage","max_articles":10}'
```

Poll the returned job and inspect ordered item-level outcomes:

```bash
curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID
curl 'http://127.0.0.1:8000/api/v1/crawls/wikipedia/JOB_ID/items?limit=100&offset=0'
```

All crawlers use bounded request sizes, descriptive user agents, rate limits,
timeouts, retry policies, canonical URLs, duplicate detection, and safe error
classification. A single failed page does not erase successful sibling pages.

## API Surface

| Area | Routes |
| --- | --- |
| Search | `GET /api/v1/search`, `GET /api/v1/search/explain`, `POST /api/v1/search/rebuild` |
| Documents | `POST/GET /api/v1/documents`, `GET/PATCH/DELETE /api/v1/documents/{id}` |
| Bulk ingestion | `POST /api/v1/documents/bulk`, `GET /api/v1/documents/bulk/{job_id}/items` |
| Jobs | `GET /api/v1/jobs/{job_id}` |
| Wikipedia | `POST /api/v1/crawls/wikipedia`, `GET /api/v1/crawls/wikipedia/{job_id}/items` |
| Medium | `POST /api/v1/crawls/medium`, `GET /api/v1/crawls/medium/{job_id}/items` |
| RSS/Atom | `POST /api/v1/crawls/rss`, `GET /api/v1/crawls/rss/{job_id}/items` |
| Health | `GET /api/v1/health` |

## Frontend Workspace

The React application has three focused views:

- `/workspace`: BM25 or TF-IDF search, ranking controls, filters, snippets, and
  score explanations.
- `/crawls`: submit a Wikipedia crawl, watch progress, and inspect page
  outcomes.
- `/library`: paginate stored documents and inspect document details.

The frontend talks to the typed FastAPI contract through a small API client.
Backend data remains authoritative; browser `localStorage` only remembers the
most recent crawl job ID so the UI can reconnect to its progress view.

## Measured Results

The following results were measured on **2026-09-05** using the local
Docker-backed stack. They are workload-specific engineering measurements, not
universal production guarantees.

| Measurement | Result | Workload |
| --- | ---: | --- |
| Backend regression suite | **584 passed, 47 skipped** | Unit and integration tests; skipped tests require external services |
| Ranking evaluation | **BM25 MRR 0.990** and **Recall@3 1.000** | 50 manually judged queries over a six-document sample corpus |
| In-memory scale build | **20,000 documents** and **20,011 terms** | Deterministic synthetic corpus; index build in **0.291-0.306 s** |
| Synthetic search latency | **35.8-37.0 ms p50**, **88.5-98.1 ms p95** | 500 warmed BM25 queries across four runs |
| Live search latency | **5.8-8.9 ms p95** | 100 HTTP requests over 2,000 matching documents |
| Async ingestion | **500/500 imported**, zero failures | Three live Celery batches; **6,922-11,666 documents/minute** |
| Wikipedia crawl | **100/100 fetched, extracted, and imported** | 100 real Featured articles at depth 0; approximately 60 seconds |
| Real-corpus index | **23,045 unique terms** | 100 real Wikipedia articles; rebuild in **0.252 s** |
| Real-corpus search | **2.799 ms p95** | 100 live HTTP requests over 73 matching articles |
| Concurrent reliability | **1,500/1,500 successful** | ApacheBench at 25, 50, and 100 concurrent clients; 239-265 req/s |

The concurrent run recorded higher p95 latency as concurrency increased on the
local single-worker API. That result is kept visible because it describes the
current capacity boundary honestly and identifies the next optimization target.

Redis recovery is also measured rather than assumed: the current snapshot stores
source documents and still rebuilds the in-memory index, so recovery was only
**1.00-1.04x** the PostgreSQL load-and-rebuild path in repeated trials. A future
compiled-postings snapshot can target a material warm-start improvement.

Full methodology, commands, raw scope, and CV-safe wording are in
[`docs/test-report.md`](docs/test-report.md).

## Verification

Backend checks from the repository root:

```bash
python -m pytest -q
python scripts/evaluate_search.py
python scripts/benchmark_search.py
```

Frontend checks from `frontend/`:

```bash
npm run lint
npm test -- --run
npm run build
```

GitHub Actions runs the backend suite against PostgreSQL 16 and Redis 7, then
runs frontend linting, tests, and a production build. The deterministic crawler
integration test uses a local fake Wikimedia boundary; live Wikipedia crawling
is manual and never required for CI.

## Repository Guide

```text
app/
  api/            FastAPI routes and dependency wiring
  search/         analyzer, inverted index, BM25, TF-IDF, evaluation
  services/       ingestion, repositories, crawlers, snapshots, job logic
  workers/        Celery application and background tasks
  models/         SQLAlchemy persistence models
  schemas/        Pydantic request and response contracts
frontend/         React + TypeScript Vite application
alembic/          PostgreSQL schema migrations
scripts/          benchmarks, evaluation, and demo utilities
tests/            unit, API, integration, and end-to-end coverage
docs/             subsystem guides and measured test report
```

Start with these deeper guides:

- [Advanced search](docs/advanced-search.md)
- [DB-backed search index](docs/db-backed-search-index.md)
- [Durable bulk ingestion](docs/bulk-ingestion.md)
- [Celery worker and process boundary](docs/celery-worker.md)
- [Wikipedia crawler](docs/wikipedia-crawler.md)
- [Frontend](docs/frontend.md)
- [PostgreSQL setup](docs/local-postgres.md)
- [Search evaluation](docs/search-evaluation.md)
- [Test report and benchmark methodology](docs/test-report.md)

## Current Scope and Next Steps

Version 1 is a focused learning product, not a general web-scale search
engine. It currently uses a process-local in-memory retrieval index, bounded
source crawlers, one shared indexing resource, and no authentication or
multi-tenant authorization layer.

Natural next milestones are:

1. Add compiled-postings snapshots and measure warm-start recovery again.
2. Add authentication, per-user libraries, and authorization boundaries.
3. Add a larger domain-specific judged query set and track ranking regressions.
4. Add semantic or hybrid retrieval only after lexical quality has a strong
   evaluation baseline.
5. Deploy API, worker, PostgreSQL, Redis, and frontend with production
   observability and independent worker scaling.

## Learning Goals

This repository is designed to make the full system explainable in an interview:

- how tokenization becomes an inverted index;
- why BM25 is used and how its score is calculated;
- how PostgreSQL differs from a search index;
- why background jobs need durable state and retries;
- how Redis coordinates processes without becoming the source of truth;
- how crawler safety, duplicate handling, and partial success work; and
- how to measure search quality, latency, throughput, and failure behavior.
