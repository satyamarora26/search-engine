from app.schemas.search_snapshots import (
    SearchIndexSnapshot,
    SearchSnapshotDocument,
)
from app.search.types import IndexedDocument
from app.services.search_index import SearchIndexService
from app.services.search_index_sync import SearchIndexSynchronizer


class FakeSnapshotStore:
    def __init__(
        self,
        active_version: str | None,
        snapshot: SearchIndexSnapshot | None = None,
        error: Exception | None = None,
    ) -> None:
        self.active_version = active_version
        self.snapshot = snapshot
        self.error = error
        self.loaded_versions: list[str] = []

    def get_active_version(self) -> str | None:
        if self.error:
            raise self.error
        return self.active_version

    def load_snapshot(self, version: str) -> SearchIndexSnapshot | None:
        self.loaded_versions.append(version)
        if self.error:
            raise self.error
        return self.snapshot


def build_local_service() -> SearchIndexService:
    return SearchIndexService(
        [IndexedDocument(id=1, title="Stable", content="uniquestable content")],
        index_version="redis-stable",
    )


def test_synchronize_activates_new_valid_snapshot():
    service = build_local_service()
    snapshot = SearchIndexSnapshot(
        index_version="redis-new",
        documents=[
            SearchSnapshotDocument(
                id=2,
                title="New",
                content="new searchable content",
                url=None,
            )
        ],
    )
    synchronizer = SearchIndexSynchronizer(
        service,
        FakeSnapshotStore("redis-new", snapshot),
    )

    synchronized = synchronizer.synchronize()

    assert synchronized is service
    assert service.search("uniquestable").total_results == 0
    assert service.search("new searchable").index_version == "redis-new"


def test_synchronize_does_not_load_matching_version():
    service = SearchIndexService(index_version="redis-current")
    store = FakeSnapshotStore("redis-current")

    SearchIndexSynchronizer(service, store).synchronize()

    assert store.loaded_versions == []


def test_synchronize_preserves_local_index_when_redis_fails(caplog):
    service = build_local_service()
    store = FakeSnapshotStore(None, error=ConnectionError("redis unavailable"))

    synchronized = SearchIndexSynchronizer(service, store).synchronize()

    assert synchronized.search("uniquestable").total_results == 1
    assert synchronized.status().index_version == "redis-stable"
    assert "Could not synchronize search index" in caplog.text


def test_synchronize_preserves_local_index_when_snapshot_is_missing(caplog):
    service = build_local_service()
    store = FakeSnapshotStore("redis-new", snapshot=None)

    SearchIndexSynchronizer(service, store).synchronize()

    assert service.search("uniquestable").total_results == 1
    assert service.status().index_version == "redis-stable"
    assert "Could not synchronize search index" in caplog.text


def test_synchronize_rejects_snapshot_with_mismatched_version(caplog):
    service = build_local_service()
    snapshot = SearchIndexSnapshot(index_version="redis-other", documents=[])

    SearchIndexSynchronizer(
        service,
        FakeSnapshotStore("redis-new", snapshot),
    ).synchronize()

    assert service.search("uniquestable").total_results == 1
    assert service.status().index_version == "redis-stable"
    assert "Could not synchronize search index" in caplog.text
