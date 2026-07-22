from typing import Literal

from pydantic import BaseModel


class HealthCheck(BaseModel):
    status: Literal["healthy", "unhealthy"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded"]
    checks: dict[str, HealthCheck]
