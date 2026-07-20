from app.workers.celery_app import celery_app


@celery_app.task(name="workers.ping")
def ping() -> dict[str, str]:
    return {"status": "ok"}
