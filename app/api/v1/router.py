from fastapi import APIRouter

from app.api.v1.crawls import router as crawls_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.medium_crawls import router as medium_crawls_router
from app.api.v1.rss_crawls import router as rss_crawls_router
from app.api.v1.search import router as search_router

router = APIRouter()
router.include_router(crawls_router)
router.include_router(documents_router)
router.include_router(health_router)
router.include_router(jobs_router)
router.include_router(medium_crawls_router)
router.include_router(rss_crawls_router)
router.include_router(search_router)
