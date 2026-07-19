import pytest

from app.search.analyzer import SimpleAnalyzer
from app.search.bm25 import Bm25Ranker
from app.search.inverted_index import InvertedIndex
from app.search.types import IndexedDocument


def build_index(documents: list[IndexedDocument]) -> InvertedIndex:
    index = InvertedIndex(analyzer=SimpleAnalyzer(stopwords=set()))
    for document in documents:
        index.add_document(document)
    return index


def test_exact_matching_document_ranks_above_unrelated_document():
    index = build_index(
        [
            IndexedDocument(id=1, title="", content="python search engine"),
            IndexedDocument(id=2, title="", content="java database cache"),
        ]
    )

    hits = Bm25Ranker().score(["python", "search"], index)

    assert [hit.document_id for hit in hits] == [1]
    assert hits[0].matched_terms == ["python", "search"]


def test_term_repetition_saturates_instead_of_growing_linearly():
    index = build_index(
        [
            IndexedDocument(id=1, title="", content="python"),
            IndexedDocument(id=2, title="", content="python python python python"),
        ]
    )

    hits = Bm25Ranker(k1=1.5, b=0).score(["python"], index)

    assert [hit.document_id for hit in hits] == [2, 1]
    assert hits[0].score < hits[1].score * 2


def test_long_document_is_not_automatically_rewarded_over_focused_document():
    index = build_index(
        [
            IndexedDocument(id=1, title="", content="python search"),
            IndexedDocument(
                id=2,
                title="",
                content="python search alpha beta gamma delta epsilon zeta eta theta",
            ),
        ]
    )

    hits = Bm25Ranker().score(["python", "search"], index)

    assert [hit.document_id for hit in hits] == [1, 2]


def test_explanation_returns_per_term_score_contribution():
    index = build_index(
        [
            IndexedDocument(id=1, title="", content="python search search"),
            IndexedDocument(id=2, title="", content="python database"),
        ]
    )

    explanation = Bm25Ranker().explain(["python", "search"], 1, index)

    assert explanation["document_id"] == 1
    assert explanation["score"] == pytest.approx(
        sum(term["contribution"] for term in explanation["terms"])
    )
    assert [term["term"] for term in explanation["terms"]] == ["python", "search"]
    assert explanation["terms"][0]["term_frequency"] == 1
    assert explanation["terms"][1]["term_frequency"] == 2
    assert explanation["terms"][1]["contribution"] > 0
