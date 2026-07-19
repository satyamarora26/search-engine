# Search Engine Architecture Design

Date: 2026-07-18

## Goal

Build a backend-only search engine from scratch as a placement-ready learning project. The system should demonstrate search fundamentals, backend architecture, persistence, caching, background processing, testing, benchmarking, and clear engineering tradeoffs.

The project will use `keshavpj1711/searchEng2.0` as a reference syllabus, not as copied code. The final result should be stronger through PostgreSQL, BM25 ranking, versioned APIs, job tracking, migrations, tests, benchmarks, and clearer documentation.

## Scope

The first product scope is a backend API. A frontend is intentionally out of scope until the backend engine is correct, tested, and explainable.

The backend will support:

- Document creation, reading, updating, deletion, and bulk ingestion.
- Wikipedia crawler ingestion through background jobs.
- Analyzer pipeline with tokenization, normalization, stopword removal, optional stemming, inverted indexing, TF-IDF ranking, and BM25 ranking.
- Search results with snippets, matched terms, ranking score, and optional scoring explanation.
- Job tracking for long-running indexing, bulk ingestion, and crawler tasks.
- Docker Compose based local deployment.
- Unit tests, integration tests, and benchmark scripts.

## Chosen Stack

- Language: Python
- API framework: FastAPI
- Database: PostgreSQL
- ORM: SQLAlchemy
- Migrations: Alembic
- Cache and broker: Redis
- Background jobs: Celery
- Testing: pytest
- Local deployment: Docker Compose

Python and FastAPI are chosen because the core learning goal is implementing search algorithms clearly. PostgreSQL is chosen over SQLite to make the backend more production-style than the reference project and to support stronger interview discussion around schema design, transactions, indexes, and migrations.

## Architecture Overview

The system is organized into layers:

1. Search core
   Pure Python implementation of analyzers, inverted index, TF-IDF, BM25, query processing, ranking, and explainability. This layer should not depend on FastAPI or the database.

2. Storage layer
   PostgreSQL stores documents, job records, crawl run records, and index version metadata. SQLAlchemy repositories isolate database access from API and search logic.

3. Service layer
   Coordinates document storage, indexing jobs, search execution, cache reads/writes, and job state transitions.

4. API layer
   FastAPI exposes versioned `/api/v1` endpoints with Pydantic request and response models.

5. Background worker layer
   Celery handles expensive work such as index rebuilds, bulk ingestion, and Wikipedia crawling.

6. Infrastructure layer
   Docker Compose runs the API, PostgreSQL, Redis, and Celery worker locally.

## Data Flow

Single document ingestion:

```text
POST /api/v1/documents
-> validate request
-> store document in PostgreSQL
-> enqueue index_document job
-> return document and job id
-> Celery updates active index/cache
```

Bulk ingestion:

```text
POST /api/v1/documents/bulk
-> validate payload
-> create bulk ingestion job
-> Celery stores documents in PostgreSQL
-> Celery updates or rebuilds index
-> job status records inserted/updated in PostgreSQL
```

Wikipedia crawler ingestion:

```text
POST /api/v1/crawl/wikipedia
-> create crawl job
-> Celery fetches article list
-> Celery fetches content concurrently with rate limits and retries
-> documents are stored in PostgreSQL
-> duplicate URLs are skipped or reported
-> index update/rebuild is triggered
-> crawl statistics are stored
```

Search:

```text
GET /api/v1/search?q=machine%20learning&ranking=bm25
-> analyze query into searchable terms
-> look up candidate documents in inverted index
-> rank candidates with BM25 or TF-IDF
-> fetch document metadata from PostgreSQL
-> return ranked results with snippets and matched terms
```

Search explanation:

```text
GET /api/v1/search/explain?q=machine%20learning&document_id=42&ranking=bm25
-> analyze query into searchable terms
-> compute per-term score contributions
-> return term frequency, document frequency, IDF, document length, and final score
```

## Search Core

The search core will be built from scratch.

Core components:

- `SimpleAnalyzer`: lowercases text, removes punctuation, splits tokens, removes stopwords, and preserves useful alphanumeric terms.
- `AdvancedAnalyzer`: starts with simple analyzer behavior, then applies stemming so related forms like `running`, `runs`, and `run` can match through a shared root term.
- `InvertedIndex`: maps each term to postings containing document id, term frequency, and scoring metadata.
- `TfidfRanker`: computes TF-IDF scores for candidate documents.
- `Bm25Ranker`: computes BM25 scores with term-frequency saturation and document-length normalization.
- `SearchEngine`: coordinates query processing, candidate selection, ranking, and explanations.

BM25 is the default ranking algorithm. TF-IDF remains available to compare ranking behavior and demonstrate the evolution from classic vector-space scoring to a stronger practical ranking model.

The analyzer should be configurable. The simple analyzer is the first stable baseline. The advanced analyzer is added after the baseline so the project can compare search quality tradeoffs: stemming can improve recall, but aggressive normalization may reduce precision.

Linear search is not part of the product. It may be mentioned in documentation as the naive baseline, but implementation effort will go directly into the inverted index.

## Persistence Model

Initial PostgreSQL tables:

- `documents`: original document title, URL, content, timestamps, and status.
- `jobs`: background job id, type, status, progress counters, error message, timestamps.
- `crawl_runs`: crawl source, requested limit, fetched count, skipped count, failed count, and status.
- `index_versions`: active index version, document count, unique term count, ranking data version, and build metadata.

PostgreSQL is the source of truth for documents and job metadata. The active search index lives in Python memory for fast query execution. Redis stores cache and coordination data.

## Redis Usage

Redis will be used for:

- Celery broker and result backend.
- Query result cache for repeated searches.
- Active index version cache.
- Optional serialized index snapshot after the first stable implementation.

Redis will not be the source of truth for documents. Cache invalidation will use index versioning: cached search results are tied to the index version that produced them.

## Background Jobs

Celery jobs:

- `index_document`: index or reindex a single document.
- `rebuild_index`: rebuild the full index from PostgreSQL.
- `bulk_ingest_documents`: validate and store many documents, then update/rebuild the index.
- `crawl_wikipedia`: fetch Wikipedia articles, store them, and trigger indexing.

The system accepts eventual consistency. After a document is created or crawled, it may take a short time before it appears in search results. The API will return job ids so clients can check progress.

## API Design

Base path:

```text
/api/v1
```

Endpoints:

```text
GET    /health
GET    /stats

POST   /documents
POST   /documents/bulk
GET    /documents/{document_id}
PUT    /documents/{document_id}
DELETE /documents/{document_id}

GET    /search
GET    /search/explain

POST   /crawl/wikipedia
GET    /jobs/{job_id}
```

Example search request:

```text
GET /api/v1/search?q=machine learning&limit=10&ranking=bm25
```

Example search response shape:

```json
{
  "query": "machine learning",
  "ranking": "bm25",
  "total_results": 2,
  "index_version": "v12",
  "results": [
    {
      "document_id": 42,
      "title": "Machine Learning",
      "url": "https://example.com/machine-learning",
      "score": 4.82,
      "snippet": "Machine learning is a field of artificial intelligence.",
      "matched_terms": ["machine", "learning"]
    }
  ]
}
```

## Error Handling

The API should return clear errors for:

- Empty or invalid search queries.
- Duplicate document URLs.
- Missing documents.
- Unsupported ranking algorithms.
- Invalid crawler limits.
- Failed background jobs.

Crawler jobs should record fetch failures without failing the entire crawl unless the source itself is unavailable.

## Testing Strategy

Unit tests:

- Simple analyzer behavior.
- Advanced analyzer stemming behavior.
- Inverted index construction.
- TF-IDF scoring.
- BM25 scoring.
- Search explanation calculations.

Integration tests:

- Document API lifecycle.
- Search API behavior.
- Job status behavior.
- Bulk ingestion behavior.
- Wikipedia crawler parsing with mocked HTTP responses.

Tests will use pytest. API tests will use FastAPI's test client or httpx. Database tests will use an isolated test database or transaction rollback fixtures.

## Benchmarks

Add `scripts/benchmark_search.py` to measure:

- Number of indexed documents.
- Unique terms.
- Index build time.
- Average search latency.
- P95 search latency.
- TF-IDF vs BM25 comparison.
- Cold cache vs warm cache comparison.

Benchmark results will be summarized in the README so performance claims have evidence.

## Docker Compose

Local services:

- `api`: FastAPI application.
- `postgres`: PostgreSQL database.
- `redis`: Redis cache and Celery broker.
- `celery_worker`: background worker for indexing and crawling.

The main local command should be:

```text
docker compose up --build
```

## Comparison With Reference Project

The reference project uses FastAPI, SQLite, Redis, Celery, Docker Compose, a Wikipedia crawler, TF-IDF, and an inverted index.

This project improves on it by adding:

- PostgreSQL instead of SQLite.
- SQLAlchemy and Alembic migrations.
- BM25 as the primary ranking algorithm.
- TF-IDF as a comparison algorithm.
- Versioned `/api/v1` API.
- Document update and delete endpoints.
- Wikipedia crawler as a tracked Celery job.
- Job status endpoint.
- Query result caching with index versioning.
- Search explanation endpoint.
- Configurable simple and advanced analyzer pipeline.
- Unit and integration tests.
- Benchmark script and evidence-backed README.

## Implementation Milestones

1. Project scaffold, dependencies, Docker Compose, and health endpoint.
2. PostgreSQL schema, SQLAlchemy models, repositories, and Alembic migrations.
3. Search core analyzer pipeline and inverted index with unit tests.
4. TF-IDF and BM25 rankers with analyzer comparison tests.
5. Document API and synchronous indexing service.
6. Search API and search explanation API.
7. Redis cache and index versioning.
8. Celery worker and job status tracking.
9. Bulk ingestion.
10. Wikipedia crawler ingestion.
11. Integration tests.
12. Benchmark script.
13. README with architecture, examples, benchmarks, and interview notes.

## Out Of Scope For First Backend Version

- Frontend UI.
- Semantic search using embeddings.
- Elasticsearch or OpenSearch.
- Kubernetes.
- Multi-node distributed index sharding.
- Cloud deployment.

These can be discussed as future extensions after the core backend is complete.
