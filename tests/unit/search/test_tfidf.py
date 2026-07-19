from app.search.analyzer import SimpleAnalyzer
from app.search.inverted_index import InvertedIndex
from app.search.tfidf import TfidfRanker
from app.search.types import IndexedDocument


def build_index() -> InvertedIndex:
    index = InvertedIndex(analyzer=SimpleAnalyzer(stopwords=set()))
    index.add_document(
        IndexedDocument(id=1, title="Python Search", content="python search search")
    )
    index.add_document(
        IndexedDocument(id=2, title="Java Search", content="java search engine")
    )
    return index


def test_document_with_higher_query_term_frequency_ranks_higher():
    index = build_index()

    hits = TfidfRanker().score(["search"], index)

    assert [hit.document_id for hit in hits] == [1, 2]
    assert hits[0].score > hits[1].score
    assert hits[0].matched_terms == ["search"]


def test_term_appearing_in_every_document_has_lower_idf_than_rare_term():
    index = InvertedIndex(analyzer=SimpleAnalyzer(stopwords=set()))
    index.add_document(IndexedDocument(id=1, title="", content="common rare"))
    index.add_document(IndexedDocument(id=2, title="", content="common"))

    ranker = TfidfRanker()
    rare_hit = ranker.score(["rare"], index)[0]
    common_hits = ranker.score(["common"], index)
    common_doc_one_hit = next(hit for hit in common_hits if hit.document_id == 1)

    assert rare_hit.document_id == 1
    assert common_doc_one_hit.document_id == 1
    assert rare_hit.score > common_doc_one_hit.score


def test_empty_query_terms_return_no_hits():
    index = build_index()

    hits = TfidfRanker().score([], index)

    assert hits == []
