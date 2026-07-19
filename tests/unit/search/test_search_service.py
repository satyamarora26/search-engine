from app.services.search import SearchService


def test_search_service_defaults_to_bm25_and_returns_metadata():
    service = SearchService.from_json_corpus("data/sample_corpus.json")

    response = service.search("bm25 ranking")

    assert response.query == "bm25 ranking"
    assert response.ranking == "bm25"
    assert response.index_version == "local-json-v1"
    assert response.total_results >= 1
    assert response.results[0].title == "BM25 Ranking"
    assert response.results[0].snippet
    assert response.results[0].matched_terms == ["bm25", "ranking"]


def test_search_service_supports_tfidf_limit():
    service = SearchService.from_json_corpus("data/sample_corpus.json")

    response = service.search("tfidf search", ranking="tfidf", limit=2)

    assert response.query == "tfidf search"
    assert response.ranking == "tfidf"
    assert len(response.results) <= 2
    assert "TF-IDF Basics" in [result.title for result in response.results]


def test_search_service_explain_returns_bm25_contributions():
    service = SearchService.from_json_corpus("data/sample_corpus.json")

    explanation = service.explain("bm25 ranking", document_id=1)

    assert explanation.query == "bm25 ranking"
    assert explanation.ranking == "bm25"
    assert explanation.document_id == 1
    assert explanation.final_score > 0
    assert [term.term for term in explanation.terms] == ["bm25", "ranking"]
