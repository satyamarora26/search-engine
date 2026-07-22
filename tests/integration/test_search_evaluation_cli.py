import subprocess
import sys


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/evaluate_search.py", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_evaluation_cli_reports_bm25_and_tfidf_metrics():
    result = run_cli()

    assert result.returncode == 0
    assert "Search evaluation" in result.stdout
    assert "Precision@3" in result.stdout
    assert "Recall@3" in result.stdout
    assert "MRR" in result.stdout
    assert "BM25" in result.stdout
    assert "TF-IDF" in result.stdout


def test_evaluation_cli_can_show_per_query_details():
    result = run_cli("--details", "--k", "2")

    assert result.returncode == 0
    assert "Per-query details" in result.stdout
    assert "bm25 ranking" in result.stdout


def test_sample_benchmark_shows_bm25_ahead_at_k_two():
    result = run_cli("--k", "2")

    assert result.returncode == 0
    ranking_rows = {
        row.split()[0]: row.split()[1:]
        for row in result.stdout.splitlines()
        if row.startswith(("BM25", "TF-IDF"))
    }

    assert ranking_rows["BM25"] == ["0.562", "0.938", "1.000"]
    assert ranking_rows["TF-IDF"] == ["0.500", "0.875", "0.938"]


def test_evaluation_cli_rejects_non_positive_k():
    result = run_cli("--k", "0")

    assert result.returncode != 0
    assert "must be at least 1" in result.stderr
