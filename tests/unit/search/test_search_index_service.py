from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.search.types import IndexedDocument
from app.services.search_index import SearchIndexService


def test_rebuild_replaces_the_current_index():
    service = SearchIndexService()

    first_status = service.rebuild(
        [
            IndexedDocument(
                id=1,
                title="Old BM25 Document",
                content="old ranking content",
            )
        ]
    )
    second_status = service.rebuild(
        [
            IndexedDocument(
                id=2,
                title="Fresh PostgreSQL Document",
                content="fresh database search content",
            )
        ]
    )

    assert first_status.document_count == 1
    assert second_status.document_count == 1
    assert service.search("old ranking").total_results == 0
    assert service.search("fresh database").results[0].document_id == 2


def test_rebuild_can_atomically_activate_a_new_index_version():
    service = SearchIndexService(index_version="redis-old")

    status = service.rebuild(
        [IndexedDocument(id=8, title="Redis", content="shared snapshot")],
        index_version="redis-new",
    )

    assert status.index_version == "redis-new"
    assert service.search("shared snapshot").index_version == "redis-new"


def test_index_document_updates_existing_document_terms():
    service = SearchIndexService()
    service.index_document(
        IndexedDocument(
            id=10,
            title="Original Title",
            content="alpha searchable content",
        )
    )

    service.index_document(
        IndexedDocument(
            id=10,
            title="Updated Title",
            content="beta searchable content",
        )
    )

    assert service.search("alpha").total_results == 0
    response = service.search("beta")
    assert response.total_results == 1
    assert response.results[0].title == "Updated Title"


def test_remove_document_deletes_it_from_search_results():
    service = SearchIndexService(
        [
            IndexedDocument(
                id=7,
                title="Delete Me",
                content="temporary searchable content",
            )
        ]
    )

    service.remove_document(7)

    assert service.search("temporary").total_results == 0


def test_explain_missing_document_raises_clear_error():
    service = SearchIndexService()

    try:
        service.explain("missing", document_id=404)
    except ValueError as error:
        assert str(error) == "Document 404 is not indexed."
    else:
        raise AssertionError("Expected missing explanation to raise ValueError.")


def test_title_scope_uses_the_matching_title_as_the_snippet():
    service = SearchIndexService(
        [
            IndexedDocument(
                id=11,
                title="Python Search Guide",
                content="A guide to a practical search engine.",
            )
        ]
    )

    response = service.search("python search", scope="title")

    assert response.results[0].snippet == "Python Search Guide"


def test_service_derives_source_host_and_copies_created_at_for_model_inputs():
    service = SearchIndexService([
        SimpleNamespace(
            id=20,
            title="Wikipedia Search",
            content="python search",
            url="https://en.wikipedia.org/wiki/Python",
            created_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        )
    ])

    response = service.search(
        "python",
        source="WIKIPEDIA.org",
        created_from=date(2026, 7, 23),
    )

    assert response.source == "wikipedia.org"
    assert response.created_from == date(2026, 7, 23)
    assert response.created_to is None
    assert response.total_results == 1
    assert response.results[0].document_id == 20


def test_service_retains_explicit_snapshot_metadata():
    service = SearchIndexService([
        IndexedDocument(
            id=21,
            title="Explicit Source Search",
            content="python search",
            source_host="example.com",
            created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        )
    ])

    response = service.search("python", source="example.com")

    assert response.total_results == 1
    assert response.results[0].document_id == 21
