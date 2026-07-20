import logging

from app.services.search_index import SearchIndexService, get_search_index_service
from app.services.search_snapshots import (
    RedisSearchIndexStore,
    create_redis_search_index_store,
)

logger = logging.getLogger(__name__)


class SearchIndexSynchronizer:
    def __init__(
        self,
        search_index: SearchIndexService,
        snapshot_store: RedisSearchIndexStore,
    ) -> None:
        self.search_index = search_index
        self.snapshot_store = snapshot_store

    def synchronize(self) -> SearchIndexService:
        try:
            active_version = self.snapshot_store.get_active_version()
            if active_version is None:
                return self.search_index
            if active_version == self.search_index.status().index_version:
                return self.search_index

            snapshot = self.snapshot_store.load_snapshot(active_version)
            if snapshot is None:
                raise ValueError(
                    f"Active search snapshot {active_version} is missing."
                )
            if snapshot.index_version != active_version:
                raise ValueError(
                    "Active search snapshot version does not match its key."
                )

            self.search_index.rebuild(
                snapshot.documents,
                index_version=active_version,
            )
        except Exception:
            logger.warning(
                "Could not synchronize search index; using local index.",
                exc_info=True,
            )
        return self.search_index


_search_index_synchronizer = SearchIndexSynchronizer(
    get_search_index_service(),
    create_redis_search_index_store(),
)


def get_synchronized_search_index_service() -> SearchIndexService:
    return _search_index_synchronizer.synchronize()
