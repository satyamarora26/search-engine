from collections.abc import Iterable
from pathlib import Path
from threading import RLock
from typing import Any

from app.schemas.search import (
    SearchExplainResponse,
    SearchExplainTerm,
    SearchIndexStatus,
    SearchResponse,
    SearchResult,
)
from app.search.corpus import load_documents_from_json
from app.search.engine import SearchEngine
from app.search.types import IndexedDocument, SearchHit, SearchScope

DEFAULT_DB_INDEX_VERSION = "postgres-memory-v1"


class SearchIndexService:
    def __init__(
        self,
        documents: Iterable[Any] | None = None,
        index_version: str = DEFAULT_DB_INDEX_VERSION,
    ) -> None:
        self.index_version = index_version
        self._lock = RLock()
        self._documents_by_id: dict[int, IndexedDocument] = {}
        self._engine = SearchEngine()
        if documents is not None:
            self.rebuild(documents)

    @classmethod
    def from_json_corpus(
        cls,
        path: str | Path,
        index_version: str,
    ) -> "SearchIndexService":
        return cls(load_documents_from_json(path), index_version=index_version)

    def rebuild(
        self,
        documents: Iterable[Any],
        *,
        index_version: str | None = None,
    ) -> SearchIndexStatus:
        indexed_documents = [_to_indexed_document(document) for document in documents]
        engine = SearchEngine()
        for document in indexed_documents:
            engine.index_document(document)

        with self._lock:
            self._engine = engine
            self._documents_by_id = {
                document.id: document
                for document in indexed_documents
            }
            if index_version is not None:
                self.index_version = index_version
            return self.status()

    def index_document(self, document: Any) -> SearchIndexStatus:
        indexed_document = _to_indexed_document(document)
        with self._lock:
            if indexed_document.id in self._documents_by_id:
                self._engine.remove_document(indexed_document.id)
            self._engine.index_document(indexed_document)
            self._documents_by_id[indexed_document.id] = indexed_document
            return self.status()

    def remove_document(self, document_id: int) -> SearchIndexStatus:
        with self._lock:
            self._engine.remove_document(document_id)
            self._documents_by_id.pop(document_id, None)
            return self.status()

    def search(
        self,
        query: str,
        ranking: str = "bm25",
        limit: int = 10,
        offset: int = 0,
        scope: SearchScope = "all",
        exact_phrase: bool = False,
    ) -> SearchResponse:
        with self._lock:
            page = self._engine.search_page(
                query,
                ranking=ranking,
                limit=limit,
                offset=offset,
                scope=scope,
                exact_phrase=exact_phrase,
            )
            results = [self._to_search_result(hit) for hit in page.hits]
            return SearchResponse(
                query=query,
                ranking=ranking,
                total_results=page.total_results,
                index_version=self.index_version,
                limit=limit,
                offset=offset,
                scope=scope,
                exact_phrase=exact_phrase,
                results=results,
            )

    def explain(
        self,
        query: str,
        document_id: int,
        ranking: str = "bm25",
    ) -> SearchExplainResponse:
        with self._lock:
            if document_id not in self._documents_by_id:
                raise ValueError(f"Document {document_id} is not indexed.")

            explanation = self._engine.explain(query, document_id, ranking=ranking)
            return SearchExplainResponse(
                query=query,
                ranking=ranking,
                document_id=document_id,
                final_score=explanation["final_score"],
                terms=[
                    SearchExplainTerm(**term)
                    for term in explanation["terms"]
                ],
            )

    def status(self) -> SearchIndexStatus:
        return SearchIndexStatus(
            index_version=self.index_version,
            document_count=len(self._documents_by_id),
        )

    def _to_search_result(self, hit: SearchHit) -> SearchResult:
        document = self._documents_by_id[hit.document_id]
        return SearchResult(
            document_id=hit.document_id,
            title=document.title,
            url=document.url,
            score=hit.score,
            snippet=_build_snippet(document, hit.matched_terms),
            matched_terms=hit.matched_terms,
        )


def _to_indexed_document(document: Any) -> IndexedDocument:
    if isinstance(document, IndexedDocument):
        return document
    return IndexedDocument(
        id=document.id,
        title=document.title,
        content=document.content,
        url=document.url,
    )


def _build_snippet(document: IndexedDocument, matched_terms: list[str]) -> str:
    lowered_terms = [term.lower() for term in matched_terms]
    for source in (document.title, document.content):
        for segment in source.split("."):
            candidate = segment.strip()
            if not candidate:
                continue
            lowered_candidate = candidate.lower()
            if any(term in lowered_candidate for term in lowered_terms):
                return candidate[:180]
    return document.content[:180]


_search_index_service = SearchIndexService()


def get_search_index_service() -> SearchIndexService:
    return _search_index_service
