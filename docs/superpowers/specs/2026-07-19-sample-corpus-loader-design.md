# Sample Corpus Loader Design

## Goal

Add a small local JSON corpus that can feed documents into the in-memory search engine before the project introduces PostgreSQL, Celery, or the Wikipedia crawler.

## Context

The search core currently supports analyzers, an inverted index, TF-IDF, BM25, and a `SearchEngine` wrapper. Tests still build documents manually in Python. The next learning step is to load a realistic document set from a file while keeping storage simple.

## Decision

Use `data/sample_corpus.json` as the first reusable corpus format.

The file will use this shape:

```json
{
  "documents": [
    {
      "id": 1,
      "title": "BM25 Ranking",
      "content": "BM25 improves TF-IDF with term saturation.",
      "url": "https://example.com/bm25"
    }
  ]
}
```

The loader will expose:

```python
load_documents_from_json(path: str | Path) -> list[IndexedDocument]
```

## Data Flow

```text
data/sample_corpus.json
  -> load_documents_from_json(path)
  -> list[IndexedDocument]
  -> SearchEngine.index_document(document)
  -> SearchEngine.search(query)
```

## Validation

The loader will raise `ValueError` when:

- the JSON root is not an object with a `documents` list
- a document is missing `id`, `title`, or `content`
- `id` is not an integer
- `title` or `content` is not a string
- `url` is present but is not a string or null

## Testing

Tests will verify:

- valid JSON documents load into `IndexedDocument` objects
- missing required fields raise a clear error
- loaded documents can be indexed and searched through `SearchEngine`

## Scope

This feature does not add PostgreSQL persistence, FastAPI endpoints, crawler logic, or background jobs. Those stay in later project phases.
