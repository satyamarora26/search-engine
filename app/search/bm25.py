import math
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass

from app.search.inverted_index import InvertedIndex
from app.search.types import SearchHit, SearchScope


@dataclass(frozen=True)
class TermScore:
    term: str
    term_frequency: int
    document_frequency: int
    idf: float
    contribution: float


class Bm25Ranker:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def score(
        self,
        query_terms: list[str],
        index: InvertedIndex,
        limit: int | None = 10,
        scope: SearchScope = "all",
        document_ids: Collection[int] | None = None,
    ) -> list[SearchHit]:
        if (
            not query_terms
            or (limit is not None and limit <= 0)
            or index.document_count(scope=scope) == 0
            or (document_ids is not None and not document_ids)
        ):
            return []

        scores: dict[int, float] = defaultdict(float)
        matched_terms: dict[int, set[str]] = defaultdict(set)

        for term in query_terms:
            for posting in index.get_postings(
                term,
                scope=scope,
                document_ids=document_ids,
            ):
                term_score = self._score_term(
                    term,
                    posting.document_id,
                    index,
                    scope=scope,
                )
                if term_score.contribution <= 0:
                    continue

                scores[posting.document_id] += term_score.contribution
                matched_terms[posting.document_id].add(term)

        hits = [
            SearchHit(
                document_id=document_id,
                score=score,
                matched_terms=sorted(matched_terms[document_id]),
            )
            for document_id, score in scores.items()
        ]
        ranked_hits = sorted(hits, key=lambda hit: (-hit.score, hit.document_id))
        return ranked_hits if limit is None else ranked_hits[:limit]

    def explain(
        self,
        query_terms: list[str],
        document_id: int,
        index: InvertedIndex,
        scope: SearchScope = "all",
    ) -> dict:
        terms = [
            self._score_term(term, document_id, index, scope=scope)
            for term in query_terms
            if index.term_frequency(document_id, term, scope=scope) > 0
        ]

        return {
            "document_id": document_id,
            "score": sum(term.contribution for term in terms),
            "terms": [
                {
                    "term": term.term,
                    "term_frequency": term.term_frequency,
                    "document_frequency": term.document_frequency,
                    "idf": term.idf,
                    "contribution": term.contribution,
                }
                for term in terms
            ],
        }

    def _score_term(
        self,
        term: str,
        document_id: int,
        index: InvertedIndex,
        scope: SearchScope = "all",
    ) -> TermScore:
        term_frequency = index.term_frequency(document_id, term, scope=scope)
        document_frequency = index.document_frequency(term, scope=scope)
        if (
            term_frequency == 0
            or document_frequency == 0
            or index.document_count(scope=scope) == 0
            or index.average_document_length(scope=scope) == 0
        ):
            return TermScore(
                term=term,
                term_frequency=term_frequency,
                document_frequency=document_frequency,
                idf=0.0,
                contribution=0.0,
            )

        idf = math.log(
            1
            + (
                (index.document_count(scope=scope) - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
        )
        document_length = index.document_length(document_id, scope=scope)
        numerator = term_frequency * (self.k1 + 1)
        denominator = term_frequency + self.k1 * (
            1
            - self.b
            + self.b
            * document_length
            / index.average_document_length(scope=scope)
        )
        contribution = idf * numerator / denominator

        return TermScore(
            term=term,
            term_frequency=term_frequency,
            document_frequency=document_frequency,
            idf=idf,
            contribution=contribution,
        )
