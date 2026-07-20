import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://search_engine:search_engine@localhost:5432/search_engine"
)


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL


def get_settings() -> Settings:
    return Settings(database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))
