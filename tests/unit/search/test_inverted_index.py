from app.search.analyzer import SimpleAnalyzer
from app.search.inverted_index import InvertedIndex
from app.search.types import IndexedDocument, Posting


def build_index() -> InvertedIndex:
    index = InvertedIndex(analyzer=SimpleAnalyzer(stopwords=set()))
    index.add_document(
        IndexedDocument(id=1, title="Python Search", content="python search search")
    )
    index.add_document(
        IndexedDocument(id=2, title="Java Search", content="java search engine")
    )
    return index


def test_term_postings_include_matching_document_ids():
    index = build_index()

    postings = index.get_postings("python")

    assert postings == [Posting(document_id=1, term_frequency=3)]


def test_term_frequency_is_counted_per_document():
    index = build_index()

    assert index.term_frequency(1, "search") == 4
    assert index.term_frequency(2, "search") == 3
    assert index.term_frequency(2, "python") == 0


def test_document_length_is_stored():
    index = build_index()

    assert index.document_length(1) == 7
    assert index.document_length(2) == 7


def test_average_document_length_is_computed():
    index = build_index()

    assert index.average_document_length() == 7.0


def test_removing_document_removes_its_postings():
    index = build_index()

    index.remove_document(1)

    assert index.get_postings("python") == []
    assert index.get_postings("search") == [Posting(document_id=2, term_frequency=3)]
    assert index.document_count() == 1
