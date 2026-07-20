import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.search_snapshots import (
    SearchIndexSnapshot,
    SearchSnapshotDocument,
)
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []
        self.fail_on_key: str | None = None

    def set(self, name: str, value: str) -> bool:
        self.set_calls.append((name, value))
        if name == self.fail_on_key:
            raise ConnectionError("redis write failed")
        self.values[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self.values.get(name)


def build_snapshot() -> SearchIndexSnapshot:
    return SearchIndexSnapshot(
        index_version="redis-task-123",
        documents=[
            SearchSnapshotDocument(
                id=1,
                title="BM25",
                content="BM25 uses term saturation.",
                url=None,
            )
        ],
    )


def test_snapshot_json_round_trip_preserves_nullable_url():
    snapshot = build_snapshot()

    restored = SearchIndexSnapshot.model_validate_json(snapshot.model_dump_json())

    assert restored == snapshot
    assert restored.format_version == 1
    assert restored.documents[0].url is None


def test_snapshot_rejects_unknown_format_version():
    with pytest.raises(ValidationError):
        SearchIndexSnapshot.model_validate(
            {"format_version": 2, "index_version": "redis-v2", "documents": []}
        )


def test_publish_writes_snapshot_before_active_pointer():
    redis = FakeRedis()
    store = RedisSearchIndexStore(redis)
    snapshot = build_snapshot()

    store.publish(snapshot)

    assert [call[0] for call in redis.set_calls] == [
        "search:index:snapshot:redis-task-123",
        "search:index:active_version",
    ]
    assert store.get_active_version() == "redis-task-123"
    assert store.load_snapshot("redis-task-123") == snapshot


def test_snapshot_write_failure_preserves_previous_active_version():
    redis = FakeRedis()
    redis.values["search:index:active_version"] = "redis-old"
    redis.fail_on_key = "search:index:snapshot:redis-task-123"
    store = RedisSearchIndexStore(redis)

    with pytest.raises(ConnectionError, match="redis write failed"):
        store.publish(build_snapshot())

    assert store.get_active_version() == "redis-old"


def test_load_snapshot_returns_none_for_missing_version():
    store = RedisSearchIndexStore(FakeRedis())

    assert store.load_snapshot("redis-missing") is None


def test_store_factory_uses_configured_redis_url_and_decoded_responses():
    store = create_redis_search_index_store(
        Settings(redis_url="redis://localhost:6379/9")
    )

    connection_options = store.client.connection_pool.connection_kwargs
    assert connection_options["host"] == "localhost"
    assert connection_options["port"] == 6379
    assert connection_options["db"] == 9
    assert connection_options["decode_responses"] is True
