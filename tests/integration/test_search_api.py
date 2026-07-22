from fastapi.testclient import TestClient

from app.main import create_app
from app.services.search import SearchService
from app.services.search_index_sync import get_synchronized_search_index_service
from app.search.types import IndexedDocument


def build_client() -> TestClient:
    app = create_app()
    search_index = SearchService.from_json_corpus("data/sample_corpus.json")
    app.dependency_overrides[
        get_synchronized_search_index_service
    ] = lambda: search_index
    return TestClient(app)


def test_search_api_defaults_to_bm25():
    client = build_client()

    response = client.get("/api/v1/search", params={"q": "bm25 ranking"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "bm25 ranking"
    assert payload["ranking"] == "bm25"
    assert payload["index_version"] == "local-json-v1"
    assert payload["results"][0]["title"] == "BM25 Ranking"
    assert payload["results"][0]["snippet"]


def test_search_api_supports_tfidf_ranking_and_limit():
    client = build_client()

    response = client.get(
        "/api/v1/search",
        params={"q": "tfidf search", "ranking": "tfidf", "limit": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ranking"] == "tfidf"
    assert len(payload["results"]) <= 2


def test_search_api_returns_pagination_and_advanced_search_metadata():
    app = create_app()
    search_index = SearchService(
        [
            IndexedDocument(
                id=1,
                title="Python Search",
                content="python search concepts",
            ),
            IndexedDocument(
                id=2,
                title="Java Search",
                content="search python concepts",
            ),
            IndexedDocument(
                id=3,
                title="Python Guide",
                content="language guide",
            ),
        ]
    )
    app.dependency_overrides[
        get_synchronized_search_index_service
    ] = lambda: search_index
    client = TestClient(app)

    response = client.get(
        "/api/v1/search",
        params={
            "q": "python search",
            "scope": "content",
            "exact_phrase": "true",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json()["total_results"] == 1
    assert response.json()["limit"] == 1
    assert response.json()["offset"] == 0
    assert response.json()["scope"] == "content"
    assert response.json()["exact_phrase"] is True
    assert [result["document_id"] for result in response.json()["results"]] == [1]


def test_search_api_rejects_invalid_scope_and_negative_offset():
    client = build_client()

    invalid_scope = client.get(
        "/api/v1/search",
        params={"q": "bm25", "scope": "metadata"},
    )
    invalid_offset = client.get(
        "/api/v1/search",
        params={"q": "bm25", "offset": -1},
    )

    assert invalid_scope.status_code == 422
    assert invalid_offset.status_code == 422


def test_search_api_rejects_invalid_ranking():
    client = build_client()

    response = client.get(
        "/api/v1/search",
        params={"q": "bm25 ranking", "ranking": "pagerank"},
    )

    assert response.status_code == 422


def test_search_api_rejects_blank_query():
    client = build_client()

    response = client.get("/api/v1/search", params={"q": "   "})

    assert response.status_code == 422


def test_search_explain_api_returns_term_contributions():
    client = build_client()

    response = client.get(
        "/api/v1/search/explain",
        params={"q": "bm25 ranking", "document_id": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "bm25 ranking"
    assert payload["ranking"] == "bm25"
    assert payload["document_id"] == 1
    assert payload["final_score"] > 0
    assert payload["terms"]


def test_search_route_uses_synchronized_index_dependency():
    app = create_app()
    search_index = SearchService.from_json_corpus("data/sample_corpus.json")
    calls = []

    def synchronized_index():
        calls.append("synchronized")
        return search_index

    app.dependency_overrides[
        get_synchronized_search_index_service
    ] = synchronized_index
    client = TestClient(app)

    response = client.get("/api/v1/search", params={"q": "bm25"})

    assert response.status_code == 200
    assert calls == ["synchronized"]
