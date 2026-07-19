import pytest

from app.search.analyzer import SimpleAnalyzer
from app.search.bm25 import Bm25Ranker
from app.search.engine import SearchEngine
from app.search.inverted_index import InvertedIndex
from app.search.tfidf import TfidfRanker
from app.search.types import IndexedDocument


def build_engine() -> tuple[SearchEngine, InvertedIndex, SimpleAnalyzer]:
    analyzer = SimpleAnalyzer(stopwords=set())
    index = InvertedIndex(analyzer=analyzer)
    engine = SearchEngine(analyzer=analyzer, index=index)
    engine.index_document(
        IndexedDocument(id=1, title="Python Search", content="python search search")
    )
    engine.index_document(
        IndexedDocument(id=2, title="Java Search", content="java search engine")
    )
    return engine, index, analyzer


def test_search_defaults_to_bm25():
    engine, index, analyzer = build_engine()

    hits = engine.search("python search")

    assert hits == Bm25Ranker().score(analyzer.analyze("python search"), index)


def test_ranking_tfidf_uses_tfidf_ranker():
    engine, index, analyzer = build_engine()

    hits = engine.search("python search", ranking="tfidf")

    assert hits == TfidfRanker().score(analyzer.analyze("python search"), index)


def test_empty_query_returns_no_hits():
    engine, _, _ = build_engine()

    hits = engine.search("   ")

    assert hits == []


def test_unsupported_ranking_raises_clear_error():
    engine, _, _ = build_engine()

    with pytest.raises(ValueError, match="Unsupported ranking"):
        engine.search("python", ranking="pagerank")


def test_remove_document_removes_it_from_search_results():
    engine, _, _ = build_engine()

    engine.remove_document(1)
    hits = engine.search("python")

    assert hits == []


def test_explain_returns_final_score_and_term_contributions():
    engine, _, _ = build_engine()

    explanation = engine.explain("python search", document_id=1)

    assert explanation["document_id"] == 1
    assert explanation["ranking"] == "bm25"
    assert explanation["final_score"] == pytest.approx(
        sum(term["contribution"] for term in explanation["terms"])
    )
    assert [term["term"] for term in explanation["terms"]] == ["python", "search"]
    assert explanation["terms"][0]["term_frequency"] == 3
    assert explanation["terms"][1]["term_frequency"] == 4
