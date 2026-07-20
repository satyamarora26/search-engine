from typing import Any
from uuid import UUID

from pydantic import BaseModel


class JobAcceptedResponse(BaseModel):
    task_id: UUID
    status: str
    status_url: str


class JobStatusResponse(BaseModel):
    task_id: UUID
    status: str
    ready: bool
    successful: bool
    result: dict[str, Any] | None = None
    error: str | None = None
