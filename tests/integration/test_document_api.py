from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.v1.documents import get_document_service
from app.main import create_app
from app.services.documents import (
    DocumentNotFoundError,
    DuplicateDocumentURLError,
)


class FakeDocument:
    def __init__(
        self,
        *,
        id: int = 1,
        title: str = "BM25 Ranking",
        content: str = "BM25 scores documents with term saturation.",
        url: str | None = "https://example.com/bm25",
        status: str = "active",
    ) -> None:
        self.id = id
        self.title = title
        self.content = content
        self.url = url
        self.status = status
        self.created_at = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
        self.updated_at = datetime(2026, 7, 20, 12, 5, tzinfo=UTC)


class FakeDocumentService:
    def __init__(self) -> None:
        self.created_with = None
        self.listed_with = None
        self.get_ids: list[int] = []
        self.updated_with = None
        self.deleted_ids: list[int] = []
        self.create_error: Exception | None = None
        self.get_error: Exception | None = None
        self.update_error: Exception | None = None
        self.delete_error: Exception | None = None

    def create_document(
        self,
        *,
        title: str,
        content: str,
        url: str | None = None,
    ) -> FakeDocument:
        self.created_with = {"title": title, "content": content, "url": url}
        if self.create_error:
            raise self.create_error
        return FakeDocument(title=title, content=content, url=url)

    def list_documents(self, *, limit: int, offset: int) -> list[FakeDocument]:
        self.listed_with = {"limit": limit, "offset": offset}
        return [
            FakeDocument(id=1, title="First document"),
            FakeDocument(id=2, title="Second document", url=None),
        ]

    def get_document(self, document_id: int) -> FakeDocument:
        self.get_ids.append(document_id)
        if self.get_error:
            raise self.get_error
        return FakeDocument(id=document_id)

    def update_document(
        self,
        document_id: int,
        *,
        changes: dict,
    ) -> FakeDocument:
        self.updated_with = {"document_id": document_id, "changes": changes}
        if self.update_error:
            raise self.update_error
        return FakeDocument(id=document_id, title=changes.get("title", "BM25 Ranking"))

    def delete_document(self, document_id: int) -> None:
        self.deleted_ids.append(document_id)
        if self.delete_error:
            raise self.delete_error


def build_client(service: FakeDocumentService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_document_service] = lambda: service
    return TestClient(app)


def test_create_document_route_returns_created_document():
    service = FakeDocumentService()
    client = build_client(service)

    response = client.post(
        "/api/v1/documents",
        json={
            "title": "  BM25 Ranking  ",
            "content": "  BM25 scores documents with term saturation.  ",
            "url": "  https://example.com/bm25  ",
        },
    )

    assert response.status_code == 201
    assert service.created_with == {
        "title": "BM25 Ranking",
        "content": "BM25 scores documents with term saturation.",
        "url": "https://example.com/bm25",
    }
    payload = response.json()
    assert payload["id"] == 1
    assert payload["title"] == "BM25 Ranking"
    assert payload["status"] == "active"


def test_create_document_route_maps_duplicate_url_to_conflict():
    service = FakeDocumentService()
    service.create_error = DuplicateDocumentURLError("Document URL already exists.")
    client = build_client(service)

    response = client.post(
        "/api/v1/documents",
        json={
            "title": "BM25 Ranking",
            "content": "BM25 scores documents with term saturation.",
            "url": "https://example.com/bm25",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Document URL already exists."


def test_create_document_route_rejects_blank_title_and_content():
    service = FakeDocumentService()
    client = build_client(service)

    response = client.post(
        "/api/v1/documents",
        json={"title": "   ", "content": "   "},
    )

    assert response.status_code == 422


def test_list_documents_route_returns_pagination_metadata():
    service = FakeDocumentService()
    client = build_client(service)

    response = client.get("/api/v1/documents", params={"limit": 2, "offset": 10})

    assert response.status_code == 200
    assert service.listed_with == {"limit": 2, "offset": 10}
    payload = response.json()
    assert payload["total_results"] == 2
    assert payload["limit"] == 2
    assert payload["offset"] == 10
    assert [document["title"] for document in payload["documents"]] == [
        "First document",
        "Second document",
    ]


def test_get_missing_document_route_returns_404():
    service = FakeDocumentService()
    service.get_error = DocumentNotFoundError("Document 99 was not found.")
    client = build_client(service)

    response = client.get("/api/v1/documents/99")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document 99 was not found."


def test_patch_document_route_sends_only_provided_fields():
    service = FakeDocumentService()
    client = build_client(service)

    response = client.patch(
        "/api/v1/documents/4",
        json={"title": "Updated title", "url": None},
    )

    assert response.status_code == 200
    assert service.updated_with == {
        "document_id": 4,
        "changes": {"title": "Updated title", "url": None},
    }


def test_patch_document_route_rejects_empty_body():
    service = FakeDocumentService()
    client = build_client(service)

    response = client.patch("/api/v1/documents/4", json={})

    assert response.status_code == 422


def test_delete_document_route_returns_204():
    service = FakeDocumentService()
    client = build_client(service)

    response = client.delete("/api/v1/documents/4")

    assert response.status_code == 204
    assert response.content == b""
    assert service.deleted_ids == [4]
