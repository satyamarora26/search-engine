# SearchEngine Test Report

**Run date:** 2026-09-05  
**Purpose:** Establish reproducible, interview-defensible numbers for the
software CV.

## Executive Summary

The backend regression suite passed **584 tests**, with **47 tests skipped**
because they require external services. The judged ranking benchmark covered
**8 queries** and produced **1.000 BM25 MRR** and **1.000 BM25 Recall@3**.

The service-backed PostgreSQL suite passed **44/44** against an isolated test
database. A live 500-document Celery batch imported **500/500 documents with
zero failures**, reaching **6,922-11,666 documents/minute** across three runs.
The live FastAPI search endpoint returned p95 latencies of **5.8-8.9 ms** over
100 requests with 2,000 matching documents.

An ApacheBench concurrency run completed **1,500/1,500 requests with zero
failures** at 25, 50, and 100 concurrent clients. On the local single-worker
API, throughput was **239-265 requests/second**; p95 latency was **263-278 ms**
at 25-50 concurrency and **555 ms** at 100 concurrency. These results expose
the current concurrency ceiling instead of treating serial latency as a
concurrent capacity claim.

A deterministic scale benchmark indexed **20,000 synthetic documents** in
approximately **0.291-0.306 seconds** across four runs. Each run measured 500
BM25 queries after a warm-up and indexed **20,011 unique terms**. Median query
latency was **35.8-37.0 ms** and p95 latency was **88.5-98.1 ms** across those
runs. This is an in-memory benchmark on a synthetic corpus, so the result does
not claim universal sub-100 ms HTTP latency for every production workload.

A live Wikipedia crawl of **100 Featured articles** completed in approximately
**60 seconds** at depth 0. All **100/100 pages were fetched and extracted**, all
**100/100 were imported**, and there were **0 fetch or ingestion failures**.
The resulting real corpus contained **23,045 unique analyzed terms** and
rebuilt in **0.252 seconds**. Over that index, 100 live `history` searches
covering 73 matching articles produced **2.799 ms p95 latency** with no failed
requests.

## Checks Run

| Area | Command | Result |
| --- | --- | --- |
| Backend unit/integration tests | `python3 -m pytest -q` | **584 passed, 47 skipped** in 16.10s |
| Ranking quality | `python3 scripts/evaluate_search.py` | 8 judged queries; BM25 Recall@3 **1.000**, MRR **1.000** |
| Scale and latency | `python3 scripts/benchmark_search.py` | 20K synthetic docs and **20,011 terms**; build **0.291-0.306s**, p50 **35.8-37.0ms**, p95 **88.5-98.1ms** across 4 runs |
| PostgreSQL/Redis service health | `docker compose ps` and `GET /api/v1/health` | PostgreSQL 16 and Redis 7 healthy; API returned HTTP 200 |
| Live PostgreSQL integration | `DATABASE_URL=...search_engine_test RUN_POSTGRES_INTEGRATION=1 python3 -m pytest tests/integration/*postgres.py -q` | **44 passed** in 5.60s |
| Live Celery ingestion | `python3 scripts/benchmark_live_ingestion.py` | 500/500 imported, 0 failed; **6,922-11,666 docs/min** across 3 runs |
| Live HTTP search | `python3 scripts/benchmark_live_search.py` | 100 requests over 2,000 matching docs; p50 **4.6-4.8ms**, p95 **5.8-8.9ms** across 3 runs |
| Concurrent HTTP search | `ab -n 500 -c 25/50/100 'http://127.0.0.1:8000/api/v1/search?q=throughput&limit=10'` | **1,500/1,500 successful**; **239-265 req/s**; p95 **263-278ms** at 25-50 concurrency and **555ms** at 100 concurrency |
| Live Wikipedia crawl | `POST /api/v1/crawls/wikipedia` with `Featured articles`, `max_articles=100`, `max_depth=0` | **100 discovered**, **100 fetched/extracted**, **100 imported**, **0 failures** in approximately **60s** |
| Real-corpus index build | Isolated PostgreSQL crawl database loaded into `SearchEngine` | **23,045 unique terms** across 100 real articles; rebuild **0.252s**; average content **25,826 characters** |
| Live real-corpus HTTP search | `DATABASE_URL=...search_engine_real_crawl_100 python3 scripts/benchmark_live_search.py --query=history --requests=100 --limit=10` | 100 requests over 73 matching articles; p50 **2.233ms**, p95 **2.799ms**, max **10.306ms** |
| Frontend lint | `npm run lint` from `frontend/` | Passed |
| Frontend tests | `npm test -- --run` from `frontend/` | Blocked by Vitest worker-start timeout in this environment; no pass count reported |
| Frontend production build | `npm exec -- vite build` from `frontend/` | Blocked by the same local process timeout; no build-pass claim reported |

## Changes Made During Test Hardening

1. Cached average document length per index scope and invalidated the cache on
   index mutations. This removes repeated full-corpus aggregation from BM25
   scoring.
2. Moved BM25 query-invariant calculations outside the per-posting scoring loop.
3. Added a fast path for unfiltered searches and streaming postings iteration
   to avoid rebuilding sorted candidate lists on every query.
4. Added indexed candidate matching and top-k selection so requests do not
   fully sort every matching document when the API asks for a small page.
5. Added `scripts/benchmark_search.py` with unique-term reporting and support
   for benchmarking a real JSON corpus later.
6. Added `scripts/benchmark_live_ingestion.py` and
   `scripts/benchmark_live_search.py` for reproducible service-level metrics.
7. Added a regression test proving average document length is refreshed after
   documents are added and removed.

## Ranking Details

The benchmark corpus contains six documents and eight manually judged queries.
The current output is:

| Ranking | Precision@3 | Recall@3 | MRR |
| --- | ---: | ---: | ---: |
| BM25 | 0.417 | 1.000 | 1.000 |
| TF-IDF | 0.417 | 1.000 | 0.938 |

This is a regression benchmark, not a claim of search quality on the whole web.
The next quality milestone should use a larger, domain-specific judged set.

## CV-Safe Numbers

These are reasonable numbers to use now, with the qualification shown:

- **584 backend tests passed**, with **47 external-service tests skipped**.
- **20,000 synthetic documents and 20,011 terms indexed in about 0.29-0.31
  seconds** in the
  deterministic benchmark.
- **36-37 ms median and 89-98 ms p95 query latency** across four 500-query
  runs on the same synthetic benchmark workload.
- **500-document asynchronous batches imported at 100% success and
  6,922-11,666 documents/minute** through FastAPI, Celery, PostgreSQL, and
  Redis on the local Docker stack.
- **5.8-8.9 ms p95 HTTP search latency** over 2,000 matching documents in 100
  requests on the local stack.
- **1,500 concurrent-load requests completed with zero failures** across
  25-100 clients; the local single-worker API sustained **239-265 req/s**.
- **100 real Wikipedia articles fetched, extracted, and imported with 100%
  success**, producing **23,045 unique terms** in an approximately 60-second
  crawl.
- **2.799 ms p95 live HTTP search latency** over a real 100-article corpus and
  73 matching documents across 100 requests.
- **8 judged queries with BM25 MRR and Recall@3 of 1.000**.
- **3 crawler source families** implemented: Wikipedia, Medium, and RSS/Atom.

Do not claim `1M+ terms`, `15x startup improvement`, or `95% extraction success`
until those values are measured with a larger corpus, a documented workload,
and the Docker-backed services running. The live p95 result is measured on the
local stack and should be labeled as such on the CV, not presented as a global
production SLO. The real-corpus result is a 100-page `Featured articles`
sample, so it should be presented as a benchmark rather than general Wikipedia
coverage.
