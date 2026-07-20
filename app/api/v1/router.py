from fastapi import APIRouter

from app.api.v1.documents import router as documents_router
from app.api.v1.search import router as search_router

router = APIRouter()
router.include_router(documents_router)
router.include_router(search_router)
