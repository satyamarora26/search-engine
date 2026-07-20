from pathlib import Path

from app.search.corpus import load_documents_from_json
from app.search.types import IndexedDocument
from app.services.search_index import SearchIndexService

DEFAULT_INDEX_VERSION = "local-json-v1"


class SearchService(SearchIndexService):
    def __init__(
        self,
        documents: list[IndexedDocument],
        index_version: str = DEFAULT_INDEX_VERSION,
    ) -> None:
        super().__init__(documents, index_version=index_version)

    @classmethod
    def from_json_corpus(cls, path: str | Path) -> "SearchService":
        return cls(load_documents_from_json(path))
