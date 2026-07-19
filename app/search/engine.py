from app.search.analyzer import BaseAnalyzer, SimpleAnalyzer
from app.search.bm25 import Bm25Ranker
from app.search.inverted_index import InvertedIndex
from app.search.tfidf import TfidfRanker
from app.search.types import IndexedDocument, SearchHit


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
    ) -> list[SearchHit]:
        query_terms = self.analyzer.analyze(query)
        if not query_terms:
            return []

        if ranking == "bm25":
            return self.bm25_ranker.score(query_terms, self.index, limit=limit)
        if ranking == "tfidf":
            return self.tfidf_ranker.score(query_terms, self.index, limit=limit)

        raise ValueError(
            f"Unsupported ranking '{ranking}'. Expected 'bm25' or 'tfidf'."
        )

    def explain(
        self,
        query: str,
        document_id: int,
        ranking: str = "bm25",
    ) -> dict:
        if ranking != "bm25":
            raise ValueError("Search explanations currently support only BM25.")

        query_terms = self.analyzer.analyze(query)
        explanation = self.bm25_ranker.explain(query_terms, document_id, self.index)

        return {
            "document_id": document_id,
            "ranking": ranking,
            "final_score": explanation["score"],
            "terms": explanation["terms"],
        }
