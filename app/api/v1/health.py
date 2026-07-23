import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import SessionLocal
from app.schemas.health import HealthCheck, HealthResponse
from app.services.search_index_sync import get_synchronized_search_index_service
from app.services.search_snapshots import create_redis_search_index_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def get_health() -> HealthResponse:
    checks = {
        "api": HealthCheck(status="healthy"),
        "database": _check_database(),
        "redis": _check_redis(),
        "search_index": _check_search_index(),
    }
    overall_status = (
        "healthy"
        if all(check.status == "healthy" for check in checks.values())
        else "degraded"
    )
    return HealthResponse(status=overall_status, checks=checks)


def _check_database() -> HealthCheck:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Health check could not reach PostgreSQL.", exc_info=True)
        return HealthCheck(
            status="unhealthy",
            detail="Database unavailable.",
        )
    return HealthCheck(status="healthy")


def _check_redis() -> HealthCheck:
    try:
        store = create_redis_search_index_store()
        store.client.ping()
    except Exception:
        logger.warning("Health check could not reach Redis.", exc_info=True)
        return HealthCheck(
            status="unhealthy",
            detail="Redis unavailable.",
        )
    return HealthCheck(status="healthy")


def _check_search_index() -> HealthCheck:
    try:
        index_status = get_synchronized_search_index_service().status()
    except Exception:
        logger.warning(
            "Health check could not read search index status.",
            exc_info=True,
        )
        return HealthCheck(
            status="unhealthy",
            detail="Search index unavailable.",
        )
    return HealthCheck(
        status="healthy",
        detail=(
            f"Index {index_status.index_version} contains "
            f"{index_status.document_count} documents."
        ),
    )
