import json
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.search.engine import SearchEngine

DEFAULT_RANKINGS = ("bm25", "tfidf")


@dataclass(frozen=True)
class EvaluationQuery:
    query: str
    relevant_document_ids: frozenset[int]

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("evaluation query cannot be blank")
        if not self.relevant_document_ids:
            raise ValueError(
                "evaluation query must have at least one relevant document"
            )


@dataclass(frozen=True)
class QueryEvaluation:
    query: str
    ranking: str
    retrieved_document_ids: tuple[int, ...]
    relevant_document_ids: frozenset[int]
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float


@dataclass(frozen=True)
class EvaluationSummary:
    ranking: str
    k: int
    query_count: int
    precision_at_k: float
    recall_at_k: float
    mean_reciprocal_rank: float
    query_results: tuple[QueryEvaluation, ...]


class SearchEvaluator:
    def __init__(self, engine: SearchEngine) -> None:
        self.engine = engine

    def evaluate(
        self,
        queries: Iterable[EvaluationQuery],
        *,
        ranking: str,
        k: int = 10,
    ) -> EvaluationSummary:
        _validate_k(k)
        evaluation_queries = tuple(queries)
        if not evaluation_queries:
            raise ValueError("at least one evaluation query is required")

        query_results = tuple(
            self._evaluate_query(query, ranking=ranking, k=k)
            for query in evaluation_queries
        )
        query_count = len(query_results)

        return EvaluationSummary(
            ranking=ranking,
            k=k,
            query_count=query_count,
            precision_at_k=(
                sum(result.precision_at_k for result in query_results)
                / query_count
            ),
            recall_at_k=(
                sum(result.recall_at_k for result in query_results) / query_count
            ),
            mean_reciprocal_rank=(
                sum(result.reciprocal_rank for result in query_results)
                / query_count
            ),
            query_results=query_results,
        )

    def evaluate_rankings(
        self,
        queries: Iterable[EvaluationQuery],
        *,
        rankings: Sequence[str] = DEFAULT_RANKINGS,
        k: int = 10,
    ) -> dict[str, EvaluationSummary]:
        evaluation_queries = tuple(queries)
        return {
            ranking: self.evaluate(evaluation_queries, ranking=ranking, k=k)
            for ranking in rankings
        }

    def _evaluate_query(
        self,
        query: EvaluationQuery,
        *,
        ranking: str,
        k: int,
    ) -> QueryEvaluation:
        hits = self.engine.search(query.query, ranking=ranking, limit=k)
        retrieved_document_ids = tuple(hit.document_id for hit in hits[:k])
        return QueryEvaluation(
            query=query.query,
            ranking=ranking,
            retrieved_document_ids=retrieved_document_ids,
            relevant_document_ids=query.relevant_document_ids,
            precision_at_k=precision_at_k(
                retrieved_document_ids,
                query.relevant_document_ids,
                k=k,
            ),
            recall_at_k=recall_at_k(
                retrieved_document_ids,
                query.relevant_document_ids,
                k=k,
            ),
            reciprocal_rank=reciprocal_rank(
                retrieved_document_ids,
                query.relevant_document_ids,
            ),
        )


def precision_at_k(
    retrieved_document_ids: Sequence[int],
    relevant_document_ids: Collection[int],
    *,
    k: int,
) -> float:
    _validate_k(k)
    relevant = _validate_relevant_documents(relevant_document_ids)
    return sum(
        document_id in relevant for document_id in retrieved_document_ids[:k]
    ) / k


def recall_at_k(
    retrieved_document_ids: Sequence[int],
    relevant_document_ids: Collection[int],
    *,
    k: int,
) -> float:
    _validate_k(k)
    relevant = _validate_relevant_documents(relevant_document_ids)
    retrieved = set(retrieved_document_ids[:k])
    return len(retrieved & relevant) / len(relevant)


def reciprocal_rank(
    retrieved_document_ids: Sequence[int],
    relevant_document_ids: Collection[int],
) -> float:
    relevant = _validate_relevant_documents(relevant_document_ids)
    for position, document_id in enumerate(retrieved_document_ids, start=1):
        if document_id in relevant:
            return 1 / position
    return 0.0


def load_evaluation_queries(path: str | Path) -> list[EvaluationQuery]:
    evaluation_path = Path(path)
    with evaluation_path.open(encoding="utf-8") as evaluation_file:
        payload = json.load(evaluation_file)

    if not isinstance(payload, dict):
        raise ValueError("evaluation root must be an object with a 'queries' list")

    raw_queries = payload.get("queries")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValueError("evaluation root must contain a non-empty 'queries' list")

    return [
        _parse_evaluation_query(raw_query, position)
        for position, raw_query in enumerate(raw_queries)
    ]


def _parse_evaluation_query(raw_query: Any, position: int) -> EvaluationQuery:
    if not isinstance(raw_query, dict):
        raise ValueError(f"query at index {position} must be an object")

    query = raw_query.get("query")
    relevant_document_ids = raw_query.get("relevant_document_ids")
    if not isinstance(query, str):
        raise ValueError(f"query at index {position} field 'query' must be a string")
    if not isinstance(relevant_document_ids, list) or not relevant_document_ids:
        raise ValueError(
            f"query at index {position} must contain a non-empty "
            "'relevant_document_ids' list"
        )
    if any(
        not isinstance(document_id, int) or isinstance(document_id, bool)
        for document_id in relevant_document_ids
    ):
        raise ValueError(
            f"query at index {position} relevant document IDs must be integers"
        )

    return EvaluationQuery(
        query=query,
        relevant_document_ids=frozenset(relevant_document_ids),
    )


def _validate_k(k: int) -> None:
    if k < 1:
        raise ValueError("k must be at least 1")


def _validate_relevant_documents(
    relevant_document_ids: Collection[int],
) -> set[int]:
    relevant = set(relevant_document_ids)
    if not relevant:
        raise ValueError("at least one relevant document is required")
    return relevant
