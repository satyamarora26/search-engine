import json
from pathlib import Path
from typing import Any

from app.search.types import IndexedDocument

REQUIRED_DOCUMENT_FIELDS = ("id", "title", "content")


def load_documents_from_json(path: str | Path) -> list[IndexedDocument]:
    corpus_path = Path(path)
    with corpus_path.open(encoding="utf-8") as corpus_file:
        payload = json.load(corpus_file)

    if not isinstance(payload, dict):
        raise ValueError("corpus root must be an object with a 'documents' list")

    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list):
        raise ValueError("corpus root must contain a 'documents' list")

    return [
        _parse_document(raw_document, position)
        for position, raw_document in enumerate(raw_documents)
    ]


def _parse_document(raw_document: Any, position: int) -> IndexedDocument:
    if not isinstance(raw_document, dict):
        raise ValueError(f"document at index {position} must be an object")

    for field in REQUIRED_DOCUMENT_FIELDS:
        if field not in raw_document:
            raise ValueError(
                f"document at index {position} missing required field '{field}'"
            )

    document_id = raw_document["id"]
    title = raw_document["title"]
    content = raw_document["content"]
    url = raw_document.get("url")

    if not isinstance(document_id, int):
        raise ValueError(f"document at index {position} field 'id' must be an integer")
    if not isinstance(title, str):
        raise ValueError(f"document at index {position} field 'title' must be a string")
    if not isinstance(content, str):
        raise ValueError(
            f"document at index {position} field 'content' must be a string"
        )
    if url is not None and not isinstance(url, str):
        raise ValueError(
            f"document at index {position} field 'url' must be a string or null"
        )

    return IndexedDocument(id=document_id, title=title, content=content, url=url)
