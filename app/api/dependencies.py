from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.services.bulk_ingestion import BulkIngestionService
from app.services.jobs import JobService
from app.workers.celery_app import celery_app
from app.workers.search_tasks import rebuild_search_index_snapshot_task


def get_job_service(
    session: Session = Depends(get_db_session),
) -> JobService:
    return JobService(session, rebuild_search_index_snapshot_task)


def get_bulk_ingestion_service(
    session: Session = Depends(get_db_session),
) -> BulkIngestionService:
    task = celery_app.signature("documents.bulk_ingest")
    return BulkIngestionService(session, task)
