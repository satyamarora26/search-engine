from typing import Protocol

from redis import Redis

from app.core.config import Settings, get_settings
from app.schemas.search_snapshots import SearchIndexSnapshot

ACTIVE_INDEX_VERSION_KEY = "search:index:active_version"
INDEX_SNAPSHOT_KEY_PREFIX = "search:index:snapshot:"


class RedisClient(Protocol):
    def set(self, name: str, value: str) -> object: ...

    def get(self, name: str) -> str | bytes | None: ...


class RedisSearchIndexStore:
    def __init__(self, client: RedisClient) -> None:
        self.client = client

    def publish(self, snapshot: SearchIndexSnapshot) -> None:
        snapshot_key = self._snapshot_key(snapshot.index_version)
        self.client.set(snapshot_key, snapshot.model_dump_json())
        self.client.set(ACTIVE_INDEX_VERSION_KEY, snapshot.index_version)

    def get_active_version(self) -> str | None:
        return _decode(self.client.get(ACTIVE_INDEX_VERSION_KEY))

    def load_snapshot(self, version: str) -> SearchIndexSnapshot | None:
        payload = self.client.get(self._snapshot_key(version))
        if payload is None:
            return None
        return SearchIndexSnapshot.model_validate_json(payload)

    @staticmethod
    def _snapshot_key(version: str) -> str:
        return f"{INDEX_SNAPSHOT_KEY_PREFIX}{version}"


def create_redis_search_index_store(
    settings: Settings | None = None,
) -> RedisSearchIndexStore:
    worker_settings = settings or get_settings()
    client = Redis.from_url(worker_settings.redis_url, decode_responses=True)
    return RedisSearchIndexStore(client)


def _decode(value: str | bytes | None) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value
