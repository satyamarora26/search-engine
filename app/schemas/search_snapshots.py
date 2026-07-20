from typing import Literal

from pydantic import BaseModel, ConfigDict


class SearchSnapshotDocument(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    url: str | None = None


class SearchIndexSnapshot(BaseModel):
    format_version: Literal[1] = 1
    index_version: str
    documents: list[SearchSnapshotDocument]
