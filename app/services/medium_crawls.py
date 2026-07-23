from collections.abc import Callable
import logging
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.job import MEDIUM_CRAWL_JOB, SEARCH_INDEX_RESOURCE, Job
from app.repositories.crawls import CrawlRepository
from app.repositories.jobs import JobRepository
from app.schemas.medium_crawls import MediumCrawlRequest
from app.services.crawl_types import CrawlItemView
from app.services.jobs import (
    IndexJobConflictError,
    JobEnqueueError,
    JobStorageError,
    TaskSender,
)
from app.services.medium_adapter import (
    medium_feed_url,
    medium_sitemap_url,
    normalize_medium_publication_url,
)

logger = logging.getLogger(__name__)


class MediumCrawlNotFoundError(Exception):
    pass


class MediumCrawlService:
    def __init__(
        self,
        session: Session,
        task: TaskSender,
        *,
        job_id_factory: Callable[[], UUID] = uuid4,
        job_repository: JobRepository | None = None,
        crawl_repository: CrawlRepository | None = None,
    ) -> None:
        self.session = session
        self.task = task
        self.job_id_factory = job_id_factory
        self.jobs = job_repository or JobRepository(session)
        self.crawls = crawl_repository or CrawlRepository(session)

    def enqueue_crawl(self, request: MediumCrawlRequest) -> Job:
        active_job = self._get_active_index_job()
        if active_job is not None:
            raise IndexJobConflictError(active_job)

        seed = normalize_medium_publication_url(request.publication_url)
        job_id = self.job_id_factory()
        try:
            job = self.jobs.create_pending(
                job_id,
                job_type=MEDIUM_CRAWL_JOB,
                resource_key=SEARCH_INDEX_RESOURCE,
                progress_total=None,
                progress_message="Waiting for worker",
            )
            self.crawls.create_run(
                job_id,
                source_key="medium",
                seed_url=seed.canonical_url,
                max_articles=request.max_articles,
                max_depth=request.max_depth,
            )
            self.crawls.add_frontier(
                job_id,
                locator=medium_feed_url(seed),
                depth=0,
            )
            self.crawls.add_frontier(
                job_id,
                locator=medium_sitemap_url(seed),
                depth=0,
            )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            winner = self._get_active_index_job()
            if winner is None:
                raise JobStorageError("Job storage unavailable.")
            raise IndexJobConflictError(winner)
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

        try:
            self.task.apply_async(args=[str(job_id)], task_id=str(job_id))
        except Exception as error:
            self._record_enqueue_failure(job_id)
            raise JobEnqueueError("Could not enqueue background job.") from error
        return job

    def list_items(
        self,
        job_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[int, list[CrawlItemView]]:
        try:
            job = self.jobs.get(job_id)
            if job is None or job.job_type != MEDIUM_CRAWL_JOB:
                raise MediumCrawlNotFoundError(
                    f"Medium crawl job {job_id} was not found."
                )
            return (
                self.crawls.count_item_views(job_id),
                self.crawls.list_item_views(
                    job_id,
                    limit=limit,
                    offset=offset,
                ),
            )
        except MediumCrawlNotFoundError:
            raise
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

    def _get_active_index_job(self) -> Job | None:
        try:
            return self.jobs.get_active_by_resource(SEARCH_INDEX_RESOURCE)
        except SQLAlchemyError as error:
            self.session.rollback()
            raise JobStorageError("Job storage unavailable.") from error

    def _record_enqueue_failure(self, job_id: UUID) -> None:
        try:
            self.jobs.mark_pending_failure(
                job_id,
                error="Could not enqueue background job.",
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            logger.exception("Could not persist enqueue failure for %s", job_id)
