import math
from collections import defaultdict

from app.search.inverted_index import InvertedIndex
from app.search.types import SearchHit, SearchScope


class TfidfRanker:
    def score(
        self,
        query_terms: list[str],
        index: InvertedIndex,
        limit: int | None = 10,
        scope: SearchScope = "all",
    ) -> list[SearchHit]:
        if (
            not query_terms
            or (limit is not None and limit <= 0)
            or index.document_count(scope=scope) == 0
        ):
            return []

        scores: dict[int, float] = defaultdict(float)
        matched_terms: dict[int, set[str]] = defaultdict(set)

        for term in query_terms:
            document_frequency = index.document_frequency(term, scope=scope)
            if document_frequency == 0:
                continue

            idf = math.log(
                (1 + index.document_count(scope=scope)) / (1 + document_frequency)
            ) + 1

            for posting in index.get_postings(term, scope=scope):
                document_length = index.document_length(
                    posting.document_id,
                    scope=scope,
                )
                if document_length == 0:
                    continue

                tf = posting.term_frequency / document_length
                scores[posting.document_id] += tf * idf
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
