# Sample Corpus Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a JSON corpus loader that turns local sample documents into `IndexedDocument` objects and proves they can be searched through `SearchEngine`.

**Architecture:** Keep ingestion separate from ranking. `app/search/corpus.py` reads and validates JSON, returning `IndexedDocument` objects. The existing `SearchEngine` remains responsible for indexing and searching.

**Tech Stack:** Python standard library `json`, `pathlib.Path`, existing `IndexedDocument`, existing `SearchEngine`, `pytest`.

## Global Constraints

- Use TDD: write tests before production code.
- Use `ValueError` for invalid corpus structure or invalid document fields.
- Do not add database, FastAPI, Celery, or crawler behavior in this task.
- Keep the corpus format compatible with later bulk ingestion: root object with a `documents` list.

---

### Task 1: JSON Corpus Loader

**Files:**
- Create: `tests/unit/search/test_corpus.py`
- Create: `app/search/corpus.py`
- Create: `data/sample_corpus.json`

**Interfaces:**
- Consumes: `IndexedDocument(id: int, title: str, content: str, url: str | None = None)`.
- Produces: `load_documents_from_json(path: str | Path) -> list[IndexedDocument]`.

- [ ] **Step 1: Write failing tests**

Create tests for:

```python
def test_loads_valid_json_documents(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text(
        '{"documents": [{"id": 1, "title": "Python", "content": "Python search", "url": null}]}'
    )

    documents = load_documents_from_json(path)

    assert documents == [
        IndexedDocument(id=1, title="Python", content="Python search", url=None)
    ]
```

```python
def test_missing_required_document_field_raises_clear_error(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text('{"documents": [{"id": 1, "title": "Python"}]}')

    with pytest.raises(ValueError, match="missing required field 'content'"):
        load_documents_from_json(path)
```

```python
def test_loaded_corpus_can_be_indexed_and_searched():
    documents = load_documents_from_json("data/sample_corpus.json")
    engine = SearchEngine()
    for document in documents:
        engine.index_document(document)

    hits = engine.search("bm25 ranking")

    assert hits
    assert hits[0].document_id == 1
```

- [ ] **Step 2: Run tests to verify red**

Run: `pytest tests/unit/search/test_corpus.py -v`

Expected: fail because `app.search.corpus` does not exist.

- [ ] **Step 3: Implement minimal loader**

Create `app/search/corpus.py` with:

```python
def load_documents_from_json(path: str | Path) -> list[IndexedDocument]:
    ...
```

Rules:

- read JSON from `path`
- require root object with `documents` list
- validate every document field
- return `IndexedDocument` objects

- [ ] **Step 4: Add sample corpus**

Create `data/sample_corpus.json` with search-engine-related documents. Document `id=1` must strongly match `bm25 ranking`.

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
pytest tests/unit/search/test_corpus.py -v
pytest tests/unit/search -v
```

Expected:

```text
All corpus tests pass
All search unit tests pass
```

- [ ] **Step 6: Commit**

Run:

```bash
git add app/search/corpus.py tests/unit/search/test_corpus.py data/sample_corpus.json
git commit -m "feat: add sample corpus loader"
```
