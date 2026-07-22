import pytest

from app.search.evaluation import (
    EvaluationQuery,
    SearchEvaluator,
    load_evaluation_queries,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.search.types import SearchHit


class FakeSearchEngine:
    def __init__(self, responses: dict[tuple[str, str], list[int]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, int]] = []

    def search(self, query: str, ranking: str, limit: int) -> list[SearchHit]:
        self.calls.append((query, ranking, limit))
        return [
            SearchHit(document_id=document_id, score=1.0, matched_terms=[])
            for document_id in self.responses.get((query, ranking), [])[:limit]
        ]


def test_metrics_measure_top_k_relevance_and_first_relevant_rank():
    retrieved = [3, 2, 4]
    relevant = {2, 4}

    assert precision_at_k(retrieved, relevant, k=3) == pytest.approx(2 / 3)
    assert recall_at_k(retrieved, relevant, k=3) == pytest.approx(1.0)
    assert reciprocal_rank(retrieved, relevant) == pytest.approx(0.5)


def test_metrics_return_zero_when_no_relevant_document_is_retrieved():
    retrieved = [3, 5]
    relevant = {2, 4}

    assert precision_at_k(retrieved, relevant, k=2) == 0.0
    assert recall_at_k(retrieved, relevant, k=2) == 0.0
    assert reciprocal_rank(retrieved, relevant) == 0.0


def test_evaluator_averages_metrics_and_requests_only_top_k_results():
    engine = FakeSearchEngine(
        {
            ("first", "bm25"): [2, 3],
            ("second", "bm25"): [5, 4],
        }
    )
    queries = [
        EvaluationQuery(query="first", relevant_document_ids=frozenset({2})),
        EvaluationQuery(query="second", relevant_document_ids=frozenset({4})),
    ]

    summary = SearchEvaluator(engine).evaluate(queries, ranking="bm25", k=2)

    assert summary.ranking == "bm25"
    assert summary.k == 2
    assert summary.query_count == 2
    assert summary.precision_at_k == pytest.approx(0.5)
    assert summary.recall_at_k == pytest.approx(1.0)
    assert summary.mean_reciprocal_rank == pytest.approx(0.75)
    assert engine.calls == [("first", "bm25", 2), ("second", "bm25", 2)]
    assert summary.query_results[1].retrieved_document_ids == (5, 4)


def test_evaluator_can_compare_multiple_rankings():
    engine = FakeSearchEngine(
        {
            ("query", "bm25"): [1, 2],
            ("query", "tfidf"): [2, 1],
        }
    )
    query = EvaluationQuery(
        query="query",
        relevant_document_ids=frozenset({1}),
    )

    summaries = SearchEvaluator(engine).evaluate_rankings([query], k=2)

    assert summaries["bm25"].mean_reciprocal_rank == pytest.approx(1.0)
    assert summaries["tfidf"].mean_reciprocal_rank == pytest.approx(0.5)


def test_loader_reads_query_judgments_from_json(tmp_path):
    path = tmp_path / "evaluation.json"
    path.write_text(
        '{"queries": [{"query": "index", '
        '"relevant_document_ids": [3, 6]}]}',
        encoding="utf-8",
    )

    queries = load_evaluation_queries(path)

    assert queries == [
        EvaluationQuery(
            query="index",
            relevant_document_ids=frozenset({3, 6}),
        )
    ]


@pytest.mark.parametrize("invalid_k", [0, -1])
def test_metrics_reject_non_positive_k(invalid_k):
    with pytest.raises(ValueError, match="k must be at least 1"):
        precision_at_k([1], {1}, k=invalid_k)
