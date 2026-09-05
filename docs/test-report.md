# SearchEngine Test Report

**Run date:** 2026-09-05  
**Purpose:** Establish reproducible, interview-defensible numbers for the
software CV.

## Executive Summary

The backend regression suite passed **584 tests**, with **47 tests skipped**
because they require external services. The judged ranking benchmark covered
**8 queries** and produced **1.000 BM25 MRR** and **1.000 BM25 Recall@3**.

A deterministic scale benchmark indexed **20,000 synthetic documents** in
approximately **0.291-0.306 seconds** across three runs. Each run measured 500
BM25 queries after a warm-up and indexed **20,011 unique terms**. Median query
latency was **36.5-37.0 ms** and p95 latency was **94.5-98.1 ms** across those
runs. This is an in-memory benchmark on a synthetic corpus, so the result does
not claim universal sub-100 ms HTTP latency for every production workload.

## Checks Run

| Area | Command | Result |
| --- | --- | --- |
| Backend unit/integration tests | `python3 -m pytest -q` | **584 passed, 47 skipped** in 27.88s |
| Ranking quality | `python3 scripts/evaluate_search.py` | 8 judged queries; BM25 Recall@3 **1.000**, MRR **1.000** |
| Scale and latency | `python3 scripts/benchmark_search.py` | 20K synthetic docs and **20,011 terms**; build **0.291-0.306s**, p50 **36.5-37.0ms**, p95 **94.5-98.1ms** across 3 runs |
| Frontend lint | `npm run lint` from `frontend/` | Passed |
| Frontend tests | `npm test -- --run` from `frontend/` | Blocked by Vitest worker-start timeout in this environment; no pass count reported |
| Frontend production build | `npm exec -- vite build` from `frontend/` | Blocked by the same local process timeout; no build-pass claim reported |
| Docker-backed integration | `docker compose ps` | Not run: Docker daemon was unavailable |

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
6. Added a regression test proving average document length is refreshed after
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
- **36-37 ms median and 94-98 ms p95 query latency** across three 500-query
  runs on the same synthetic benchmark workload.
- **8 judged queries with BM25 MRR and Recall@3 of 1.000**.
- **3 crawler source families** implemented: Wikipedia, Medium, and RSS/Atom.

Do not claim `1M+ terms`, `15x startup improvement`, or `95% extraction success`
until those values are measured with a larger corpus, a documented workload,
and the Docker-backed services running. The p95 result above is under 100 ms for
the documented synthetic in-memory workload; label it that way on the CV.
