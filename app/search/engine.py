from datetime import date

from app.search.analyzer import BaseAnalyzer, SimpleAnalyzer
from app.search.bm25 import Bm25Ranker
from app.search.filters import normalize_source
from app.search.inverted_index import InvertedIndex
from app.search.tfidf import TfidfRanker
from app.search.types import IndexedDocument, SearchHit, SearchPage, SearchScope


class SearchEngine:
    def __init__(
        self,
        analyzer: BaseAnalyzer | None = None,
        index: InvertedIndex | None = None,
        bm25_ranker: Bm25Ranker | None = None,
        tfidf_ranker: TfidfRanker | None = None,
    ) -> None:
        self.analyzer = analyzer if analyzer is not None else SimpleAnalyzer()
        self.index = index if index is not None else InvertedIndex(self.analyzer)
        self.bm25_ranker = bm25_ranker if bm25_ranker is not None else Bm25Ranker()
        self.tfidf_ranker = (
            tfidf_ranker if tfidf_ranker is not None else TfidfRanker()
        )

    def index_document(self, document: IndexedDocument) -> None:
        self.index.add_document(document)

    def remove_document(self, document_id: int) -> None:
        self.index.remove_document(document_id)

    def search(
        self,
        query: str,
        ranking: str = "bm25",
        limit: int = 10,
        offset: int = 0,
        scope: SearchScope = "all",
        exact_phrase: bool = False,
        source: str | None = None,
        created_from: date | None = None,
        created_to: date | None = None,
    ) -> list[SearchHit]:
        return self.search_page(
            query,
            ranking=ranking,
            limit=limit,
            offset=offset,
            scope=scope,
            exact_phrase=exact_phrase,
            source=source,
            created_from=created_from,
            created_to=created_to,
        ).hits

    def search_page(
        self,
        query: str,
        ranking: str = "bm25",
        limit: int = 10,
        offset: int = 0,
        scope: SearchScope = "all",
        exact_phrase: bool = False,
        source: str | None = None,
        created_from: date | None = None,
        created_to: date | None = None,
    ) -> SearchPage:
        if offset < 0:
            raise ValueError("offset must be at least 0")

        query_terms = self.analyzer.analyze(query)
        if not query_terms:
            return SearchPage(hits=[], total_results=0)

        normalized_source = normalize_source(source)
        has_filters = (
            normalized_source is not None
            or created_from is not None
            or created_to is not None
        )
        candidate_ids = (
            self.index.filter_document_ids(
                source=normalized_source,
                created_from=created_from,
                created_to=created_to,
            )
            if has_filters
            else None
        )
        ranked_limit = (
            len(candidate_ids)
            if candidate_ids is not None
            else self.index.document_count(scope=scope)
        )

        if ranking == "bm25":
            ranked_hits = self.bm25_ranker.score(
                query_terms,
                self.index,
                limit=ranked_limit,
                scope=scope,
                document_ids=candidate_ids,
            )
        elif ranking == "tfidf":
            ranked_hits = self.tfidf_ranker.score(
                query_terms,
                self.index,
                limit=ranked_limit,
                scope=scope,
                document_ids=candidate_ids,
            )
        else:
            raise ValueError(
                f"Unsupported ranking '{ranking}'. Expected 'bm25' or 'tfidf'."
            )

        if exact_phrase:
            ranked_hits = [
                hit
                for hit in ranked_hits
                if self.index.contains_phrase(
                    hit.document_id,
                    query_terms,
                    scope=scope,
                )
            ]

        return SearchPage(
            hits=ranked_hits[offset : offset + limit],
            total_results=len(ranked_hits),
        )

    def explain(
        self,
        query: str,
        document_id: int,
        ranking: str = "bm25",
        scope: SearchScope = "all",
    ) -> dict:
        if ranking != "bm25":
            raise ValueError("Search explanations currently support only BM25.")

        query_terms = self.analyzer.analyze(query)
        explanation = self.bm25_ranker.explain(
            query_terms,
            document_id,
            self.index,
            scope=scope,
        )

        return {
            "document_id": document_id,
            "ranking": ranking,
            "final_score": explanation["score"],
            "terms": explanation["terms"],
        }
