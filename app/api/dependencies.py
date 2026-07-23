from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.services.bulk_ingestion import BulkIngestionService
from app.services.jobs import JobService
from app.services.wikipedia_crawls import WikipediaCrawlService
from app.services.medium_crawls import MediumCrawlService
from app.services.rss_crawls import RssCrawlService
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


def get_wikipedia_crawl_service(
    session: Session = Depends(get_db_session),
) -> WikipediaCrawlService:
    task = celery_app.signature("wikipedia.crawl")
    return WikipediaCrawlService(session, task)


def get_medium_crawl_service(
    session: Session = Depends(get_db_session),
) -> MediumCrawlService:
    task = celery_app.signature("crawl.medium")
    return MediumCrawlService(session, task)


def get_rss_crawl_service(
    session: Session = Depends(get_db_session),
) -> RssCrawlService:
    task = celery_app.signature("crawl.rss")
    return RssCrawlService(session, task)
