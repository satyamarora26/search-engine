from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db.session import engine


class JobAlreadyRunningError(Exception):
    pass


class PostgresAdvisoryLock:
    def __init__(
        self,
        connection_factory: Callable[[], Connection] = engine.connect,
    ) -> None:
        self.connection_factory = connection_factory

    @contextmanager
    def acquire(self, job_id: UUID) -> Iterator[None]:
        connection = self.connection_factory()
        try:
            lock_key = str(job_id)
            acquired = connection.scalar(
                text(
                    "select pg_try_advisory_lock("
                    "hashtextextended(:key, 0))"
                ),
                {"key": lock_key},
            )
            if not acquired:
                raise JobAlreadyRunningError(
                    f"Job {job_id} is already running."
                )
            try:
                yield
            finally:
                connection.execute(
                    text(
                        "select pg_advisory_unlock("
                        "hashtextextended(:key, 0))"
                    ),
                    {"key": lock_key},
                )
        finally:
            connection.close()
