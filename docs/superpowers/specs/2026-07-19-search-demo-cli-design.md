# Search Demo CLI Design

## Goal

Add a tiny command-line demo that searches the local JSON sample corpus through the existing in-memory search engine.

## Command

```bash
python scripts/search_demo.py --query "bm25 ranking"
```

Optional flags:

```bash
python scripts/search_demo.py --query "tfidf search" --ranking tfidf --limit 3
python scripts/search_demo.py --query "crawler" --corpus data/sample_corpus.json
```

## Data Flow

```text
CLI arguments
  -> load_documents_from_json(corpus)
  -> SearchEngine.index_document(document)
  -> SearchEngine.search(query, ranking, limit)
  -> print readable results with metadata from loaded documents
```

## Output

The command will print:

- query
- ranking algorithm
- result count
- each result title
- score rounded to three decimals
- matched terms
- URL when present

Example:

```text
Query: bm25 ranking
Ranking: bm25
Results: 1

1. BM25 Ranking
   Score: 1.234
   Matched terms: bm25, ranking
   URL: https://example.com/search/bm25-ranking
```

## Validation

The CLI will use `argparse` for validation:

- `--query` is required
- `--ranking` must be `bm25` or `tfidf`
- `--limit` defaults to `5`
- `--corpus` defaults to `data/sample_corpus.json`

## Scope

This feature does not start a server, add FastAPI, use PostgreSQL, or implement interactive shell behavior. It is only a deterministic local demo for learning and manual verification.
