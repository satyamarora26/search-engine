# Search Demo CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a runnable CLI command that searches `data/sample_corpus.json` through the existing `SearchEngine`.

**Architecture:** Keep the CLI as a thin adapter. `scripts/search_demo.py` parses arguments, loads documents with `load_documents_from_json`, indexes them into `SearchEngine`, runs search, and formats results using the already-loaded document metadata.

**Tech Stack:** Python standard library `argparse`, `pathlib`, `sys`; existing `load_documents_from_json`; existing `SearchEngine`; `pytest`; `subprocess` for integration-style CLI tests.

## Global Constraints

- Use TDD: write tests before production code.
- The default command must be `python scripts/search_demo.py --query "bm25 ranking"`.
- `--ranking` must accept only `bm25` and `tfidf`.
- `--limit` must default to `5`.
- `--corpus` must default to `data/sample_corpus.json`.
- Do not add FastAPI, PostgreSQL, Celery, or interactive shell behavior in this task.

---

### Task 1: Search Demo CLI

**Files:**
- Create: `scripts/search_demo.py`
- Create: `tests/integration/test_search_demo_cli.py`

**Interfaces:**
- Consumes: `load_documents_from_json(path: str | Path) -> list[IndexedDocument]`.
- Consumes: `SearchEngine.search(query: str, ranking: str = "bm25", limit: int = 10) -> list[SearchHit]`.
- Produces: CLI command `python scripts/search_demo.py --query "bm25 ranking"`.

- [ ] **Step 1: Write failing CLI tests**

Create `tests/integration/test_search_demo_cli.py` with:

```python
import subprocess
import sys


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/search_demo.py", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_returns_results_for_default_bm25_search():
    result = run_cli("--query", "bm25 ranking")

    assert result.returncode == 0
    assert "Query: bm25 ranking" in result.stdout
    assert "Ranking: bm25" in result.stdout
    assert "1. BM25 Ranking" in result.stdout
    assert "Matched terms: bm25, ranking" in result.stdout
```

```python
def test_cli_supports_tfidf_ranking():
    result = run_cli("--query", "tfidf search", "--ranking", "tfidf", "--limit", "2")

    assert result.returncode == 0
    assert "Ranking: tfidf" in result.stdout
    assert "TF-IDF Basics" in result.stdout
```

```python
def test_cli_rejects_invalid_ranking():
    result = run_cli("--query", "python", "--ranking", "pagerank")

    assert result.returncode != 0
    assert "invalid choice" in result.stderr
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
pytest tests/integration/test_search_demo_cli.py -v
```

Expected: fail because `scripts/search_demo.py` does not exist.

- [ ] **Step 3: Implement CLI**

Create `scripts/search_demo.py` with:

```python
def main() -> int:
    ...


if __name__ == "__main__":
    raise SystemExit(main())
```

The command must parse `--query`, `--ranking`, `--limit`, and `--corpus`, then print readable ranked results.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
pytest tests/integration/test_search_demo_cli.py -v
pytest tests/unit/search tests/integration -v
```

Expected:

```text
All CLI tests pass
All search and integration tests pass
```

- [ ] **Step 5: Commit**

Run:

```bash
git add scripts/search_demo.py tests/integration/test_search_demo_cli.py
git commit -m "feat: add search demo cli"
```
