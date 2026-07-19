import math
from collections import defaultdict

from app.search.inverted_index import InvertedIndex
from app.search.types import SearchHit


class TfidfRanker:
    def score(
        self,
        query_terms: list[str],
        index: InvertedIndex,
        limit: int = 10,
    ) -> list[SearchHit]:
        if not query_terms or limit <= 0:
            return []

        scores: dict[int, float] = defaultdict(float)
        matched_terms: dict[int, set[str]] = defaultdict(set)

        for term in query_terms:
            document_frequency = index.document_frequency(term)
            if document_frequency == 0:
                continue

            idf = math.log(
                (1 + index.document_count()) / (1 + document_frequency)
            ) + 1

            for posting in index.get_postings(term):
                document_length = index.document_length(posting.document_id)
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
        return sorted(hits, key=lambda hit: (-hit.score, hit.document_id))[:limit]
