from pathlib import Path

from app.schemas.search import (
    SearchExplainResponse,
    SearchExplainTerm,
    SearchResponse,
    SearchResult,
)
from app.search.corpus import load_documents_from_json
from app.search.engine import SearchEngine
from app.search.types import IndexedDocument, SearchHit

DEFAULT_INDEX_VERSION = "local-json-v1"


class SearchService:
    def __init__(
        self,
        documents: list[IndexedDocument],
        index_version: str = DEFAULT_INDEX_VERSION,
    ) -> None:
        self.index_version = index_version
        self.documents_by_id = {document.id: document for document in documents}
        self.engine = SearchEngine()
        for document in documents:
            self.engine.index_document(document)

    @classmethod
    def from_json_corpus(cls, path: str | Path) -> "SearchService":
        return cls(load_documents_from_json(path))

    def search(
        self,
        query: str,
        ranking: str = "bm25",
        limit: int = 10,
    ) -> SearchResponse:
        hits = self.engine.search(query, ranking=ranking, limit=limit)
        results = [self._to_search_result(hit) for hit in hits]
        return SearchResponse(
            query=query,
            ranking=ranking,
            total_results=len(results),
            index_version=self.index_version,
            results=results,
        )

    def explain(
        self,
        query: str,
        document_id: int,
        ranking: str = "bm25",
    ) -> SearchExplainResponse:
        if document_id not in self.documents_by_id:
            raise ValueError(f"Document {document_id} is not indexed.")

        explanation = self.engine.explain(query, document_id, ranking=ranking)
        return SearchExplainResponse(
            query=query,
            ranking=ranking,
            document_id=document_id,
            final_score=explanation["final_score"],
            terms=[SearchExplainTerm(**term) for term in explanation["terms"]],
        )

    def _to_search_result(self, hit: SearchHit) -> SearchResult:
        document = self.documents_by_id[hit.document_id]
        return SearchResult(
            document_id=hit.document_id,
            title=document.title,
            url=document.url,
            score=hit.score,
            snippet=_build_snippet(document.content, hit.matched_terms),
            matched_terms=hit.matched_terms,
        )


def _build_snippet(content: str, matched_terms: list[str]) -> str:
    lowered_terms = [term.lower() for term in matched_terms]
    for segment in content.split("."):
        candidate = segment.strip()
        if not candidate:
            continue
        lowered_candidate = candidate.lower()
        if any(term in lowered_candidate for term in lowered_terms):
            return candidate[:180]
    return content[:180]
