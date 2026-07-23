from celery import Celery

from app.core.config import Settings, get_settings


def create_celery_app(settings: Settings | None = None) -> Celery:
    worker_settings = settings or get_settings()
    celery_app = Celery(
        "search_engine",
        broker=worker_settings.celery_broker_url,
        backend=worker_settings.celery_result_backend,
    )
    celery_app.conf.update(
        imports=(
            "app.workers.tasks",
            "app.workers.search_tasks",
            "app.workers.ingestion_tasks",
            "app.workers.wikipedia_tasks",
            "app.workers.crawl_tasks",
        ),
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
    )
    return celery_app


celery_app = create_celery_app()
