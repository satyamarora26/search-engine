from fastapi import FastAPI

from app.api.v1.router import router as v1_router


def create_app() -> FastAPI:
    app = FastAPI(title="Search Engine API")
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
