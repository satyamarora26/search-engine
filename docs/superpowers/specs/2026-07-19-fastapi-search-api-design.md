# FastAPI Search API Design

## Goal

Expose the existing in-memory search engine through HTTP endpoints before adding PostgreSQL. This turns the search core into a backend API that can be tested and later connected to persistent storage.

## Endpoints

```text
GET /api/v1/search?q=bm25 ranking
GET /api/v1/search?q=tfidf search&ranking=tfidf&limit=3
GET /api/v1/search/explain?q=bm25 ranking&document_id=1
```

## Data Source

For this phase, the API loads:

```text
data/sample_corpus.json
```

The corpus is indexed in memory when the app is created. Later, this initialization path will be replaced by loading active documents from PostgreSQL.

## Data Flow

```text
HTTP request
  -> FastAPI validates query parameters
  -> route calls SearchEngine
  -> SearchEngine uses Analyzer + InvertedIndex + BM25/TF-IDF
  -> route enriches hits with loaded document metadata
  -> JSON response
```

## Search Response

Each result will include:

- `document_id`
- `title`
- `url`
- `score`
- `snippet`
- `matched_terms`

The response will include:

- `query`
- `ranking`
- `total_results`
- `index_version`
- `results`

For now, `index_version` will be the static value `local-json-v1`.

## Explain Response

The explain endpoint will return:

- `query`
- `ranking`
- `document_id`
- `final_score`
- per-term contribution data from BM25

For this phase, explanations support BM25 only.

## Validation

FastAPI should return validation errors when:

- `q` is missing or blank
- `ranking` is not `bm25` or `tfidf`
- `limit` is outside `1..50`
- `document_id` is missing for explain

## Scope

This feature does not add PostgreSQL, SQLAlchemy, Redis, Celery, Docker, document CRUD endpoints, or crawler endpoints. It only exposes the current JSON-backed search engine through FastAPI.
