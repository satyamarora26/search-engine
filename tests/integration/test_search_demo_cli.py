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


def test_cli_supports_tfidf_ranking():
    result = run_cli("--query", "tfidf search", "--ranking", "tfidf", "--limit", "2")

    assert result.returncode == 0
    assert "Ranking: tfidf" in result.stdout
    assert "TF-IDF Basics" in result.stdout


def test_cli_rejects_invalid_ranking():
    result = run_cli("--query", "python", "--ranking", "pagerank")

    assert result.returncode != 0
    assert "invalid choice" in result.stderr
