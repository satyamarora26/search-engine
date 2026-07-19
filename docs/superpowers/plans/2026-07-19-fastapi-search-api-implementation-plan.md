# FastAPI Search API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FastAPI endpoints that expose the existing JSON-backed `SearchEngine` over HTTP.

**Architecture:** Keep the API as a thin HTTP adapter. `app/main.py` creates the FastAPI app, `app/api/v1/router.py` groups v1 routes, `app/api/v1/search.py` handles search endpoints, `app/schemas/search.py` defines response models, and `app/services/search.py` owns the JSON-backed search engine instance plus metadata enrichment.

**Tech Stack:** FastAPI, Pydantic, Python standard library, existing `SearchEngine`, existing `load_documents_from_json`, pytest, FastAPI `TestClient`.

## Global Constraints

- Use TDD: write tests before production code.
- Add `fastapi` to `requirements.txt`.
- Use `data/sample_corpus.json` as the API data source for this phase.
- Default ranking must be `bm25`.
- Supported ranking values are `bm25` and `tfidf`.
- Search `limit` must be from `1` to `50`.
- API `index_version` must be `local-json-v1`.
- Do not add PostgreSQL, SQLAlchemy, Redis, Celery, Docker, document CRUD endpoints, or crawler endpoints in this task.

---

### Task 1: Search API Schemas And Service

**Files:**
- Modify: `requirements.txt`
- Create: `app/schemas/__init__.py`
- Create: `app/schemas/search.py`
- Create: `app/services/__init__.py`
- Create: `app/services/search.py`
- Test: `tests/unit/search/test_search_service.py`

**Interfaces:**
- Consumes: `load_documents_from_json(path: str | Path) -> list[IndexedDocument]`.
- Consumes: `SearchEngine.search(query: str, ranking: str = "bm25", limit: int = 10) -> list[SearchHit]`.
- Consumes: `SearchEngine.explain(query: str, document_id: int, ranking: str = "bm25") -> dict`.
- Produces: `SearchService.search(query: str, ranking: str = "bm25", limit: int = 10) -> SearchResponse`.
- Produces: `SearchService.explain(query: str, document_id: int, ranking: str = "bm25") -> SearchExplainResponse`.

- [ ] **Step 1: Write failing service tests**

Create tests that assert:

```python
service = SearchService.from_json_corpus("data/sample_corpus.json")
response = service.search("bm25 ranking")
assert response.ranking == "bm25"
assert response.total_results >= 1
assert response.results[0].title == "BM25 Ranking"
```

```python
response = service.search("tfidf search", ranking="tfidf", limit=2)
assert response.ranking == "tfidf"
assert len(response.results) <= 2
```

```python
explanation = service.explain("bm25 ranking", document_id=1)
assert explanation.ranking == "bm25"
assert explanation.final_score > 0
assert explanation.terms
```

- [ ] **Step 2: Run service tests to verify red**

Run:

```bash
pytest tests/unit/search/test_search_service.py -v
```

Expected: fail because `app.services.search` does not exist.

- [ ] **Step 3: Implement schemas and service**

Create Pydantic response models:

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

class SearchExplainTerm(BaseModel):
    term: str
    term_frequency: int
    document_frequency: int
    idf: float
    contribution: float

class SearchExplainResponse(BaseModel):
    query: str
    ranking: str
    document_id: int
    final_score: float
    terms: list[SearchExplainTerm]
```

Service rules:

- load documents from JSON
- index documents into `SearchEngine`
- map `SearchHit` objects to `SearchResult`
- generate a snippet from the first content segment containing a matched term, otherwise first 180 characters

- [ ] **Step 4: Run service tests**

Run:

```bash
pytest tests/unit/search/test_search_service.py -v
```

Expected: all service tests pass.

---

### Task 2: FastAPI Routes

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/v1/__init__.py`
- Create: `app/api/v1/router.py`
- Create: `app/api/v1/search.py`
- Create: `app/main.py`
- Test: `tests/integration/test_search_api.py`

**Interfaces:**
- Consumes: `SearchService.search(query: str, ranking: str = "bm25", limit: int = 10) -> SearchResponse`.
- Consumes: `SearchService.explain(query: str, document_id: int, ranking: str = "bm25") -> SearchExplainResponse`.
- Produces: `create_app() -> FastAPI`.
- Produces: `GET /api/v1/search`.
- Produces: `GET /api/v1/search/explain`.

- [ ] **Step 1: Write failing API tests**

Create tests that assert:

```python
client = TestClient(create_app())
response = client.get("/api/v1/search", params={"q": "bm25 ranking"})
assert response.status_code == 200
assert response.json()["ranking"] == "bm25"
assert response.json()["results"][0]["title"] == "BM25 Ranking"
```

```python
response = client.get("/api/v1/search", params={"q": "tfidf search", "ranking": "tfidf", "limit": 2})
assert response.status_code == 200
assert response.json()["ranking"] == "tfidf"
assert len(response.json()["results"]) <= 2
```

```python
response = client.get("/api/v1/search", params={"q": "bm25 ranking", "ranking": "pagerank"})
assert response.status_code == 422
```

```python
response = client.get("/api/v1/search", params={"q": "   "})
assert response.status_code == 422
```

```python
response = client.get("/api/v1/search/explain", params={"q": "bm25 ranking", "document_id": 1})
assert response.status_code == 200
assert response.json()["final_score"] > 0
assert response.json()["terms"]
```

- [ ] **Step 2: Run API tests to verify red**

Run:

```bash
pytest tests/integration/test_search_api.py -v
```

Expected: fail because `app.main` and API routes do not exist.

- [ ] **Step 3: Implement FastAPI app and routes**

Rules:

- create `create_app() -> FastAPI`
- include v1 router under `/api/v1`
- use query parameter alias `q`
- validate blank query with `HTTPException(status_code=422)`
- use `Literal["bm25", "tfidf"]` for ranking validation
- use `Query(ge=1, le=50)` for limit validation

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
pytest tests/unit/search/test_search_service.py tests/integration/test_search_api.py -v
pytest tests/unit/search tests/integration -v
```

Expected:

```text
All search service and API tests pass
All search unit and integration tests pass
```

- [ ] **Step 5: Commit and push**

Run:

```bash
git add requirements.txt app/schemas app/services app/api app/main.py tests/unit/search/test_search_service.py tests/integration/test_search_api.py
git commit -m "feat: add fastapi search api"
git push
```
