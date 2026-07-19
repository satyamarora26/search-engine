import pytest

from app.search.corpus import load_documents_from_json
from app.search.engine import SearchEngine
from app.search.types import IndexedDocument


def test_loads_valid_json_documents(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text(
        '{"documents": [{"id": 1, "title": "Python", '
        '"content": "Python search", "url": null}]}'
    )

    documents = load_documents_from_json(path)

    assert documents == [
        IndexedDocument(id=1, title="Python", content="Python search", url=None)
    ]


def test_missing_required_document_field_raises_clear_error(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text('{"documents": [{"id": 1, "title": "Python"}]}')

    with pytest.raises(ValueError, match="missing required field 'content'"):
        load_documents_from_json(path)


def test_loaded_corpus_can_be_indexed_and_searched():
    documents = load_documents_from_json("data/sample_corpus.json")
    engine = SearchEngine()
    for document in documents:
        engine.index_document(document)

    hits = engine.search("bm25 ranking")

    assert hits
    assert hits[0].document_id == 1
