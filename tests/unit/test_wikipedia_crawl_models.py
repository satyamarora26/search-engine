from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.wikipedia_crawl import (
    WikipediaCrawlFrontier,
    WikipediaCrawlPage,
    WikipediaCrawlRun,
)


def constraint_names(model):
    return {constraint.name for constraint in model.__table__.constraints}


def index_names(model):
    return {index.name for index in model.__table__.indexes}


def compile_table(model):
    return str(
        CreateTable(model.__table__).compile(dialect=postgresql.dialect())
    )


def test_crawl_run_has_request_and_discovery_checkpoint_columns():
    assert {
        "job_id",
        "root_category",
        "max_articles",
        "max_depth",
        "discovery_complete",
        "category_limit_reached",
        "created_at",
        "updated_at",
    } == set(WikipediaCrawlRun.__table__.columns.keys())


def test_frontier_has_durable_breadth_first_checkpoint_columns():
    assert {
        "id",
        "job_id",
        "category_title",
        "depth",
        "continuation",
        "status",
        "error",
        "created_at",
        "updated_at",
    } == set(WikipediaCrawlFrontier.__table__.columns.keys())
    assert (
        WikipediaCrawlFrontier.__table__.c.continuation.type.none_as_null
        is True
    )


def test_page_has_fetch_and_ingestion_link_columns():
    assert {
        "id",
        "job_id",
        "position",
        "wikipedia_page_id",
        "title",
        "canonical_url",
        "fetch_status",
        "fetch_attempts",
        "ingestion_item_id",
        "error",
        "fetched_at",
        "created_at",
        "updated_at",
    } == set(WikipediaCrawlPage.__table__.columns.keys())


def test_crawler_models_declare_named_constraints_and_indexes():
    assert {
        "wikipedia_crawl_runs_article_limit_check",
        "wikipedia_crawl_runs_depth_check",
    } <= constraint_names(WikipediaCrawlRun)
    assert {
        "wikipedia_crawl_frontier_job_category_key",
        "wikipedia_crawl_frontier_depth_check",
        "wikipedia_crawl_frontier_status_check",
        "wikipedia_crawl_frontier_outcome_check",
    } <= constraint_names(WikipediaCrawlFrontier)
    assert {
        "wikipedia_crawl_pages_job_position_key",
        "wikipedia_crawl_pages_job_page_key",
        "wikipedia_crawl_pages_position_check",
        "wikipedia_crawl_pages_attempts_check",
        "wikipedia_crawl_pages_status_check",
        "wikipedia_crawl_pages_outcome_check",
        "wikipedia_crawl_pages_ingestion_item_key",
    } <= constraint_names(WikipediaCrawlPage)
    assert index_names(WikipediaCrawlFrontier) == {
        "wikipedia_crawl_frontier_job_status_depth_idx"
    }
    assert index_names(WikipediaCrawlPage) == {
        "wikipedia_crawl_pages_job_status_position_idx"
    }


def test_crawler_models_compile_postgresql_types_and_foreign_keys():
    run_sql = compile_table(WikipediaCrawlRun)
    frontier_sql = compile_table(WikipediaCrawlFrontier)
    page_sql = compile_table(WikipediaCrawlPage)

    assert "FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE" in run_sql
    assert (
        "FOREIGN KEY(job_id) REFERENCES wikipedia_crawl_runs (job_id) "
        "ON DELETE CASCADE"
    ) in frontier_sql
    assert "JSON" in frontier_sql
    assert "JSONB" not in frontier_sql
    assert (
        "FOREIGN KEY(job_id) REFERENCES wikipedia_crawl_runs (job_id) "
        "ON DELETE CASCADE"
    ) in page_sql
    assert (
        "FOREIGN KEY(ingestion_item_id) REFERENCES ingestion_items (id) "
        "ON DELETE CASCADE"
    ) in page_sql
    assert "TIMESTAMP WITH TIME ZONE" in page_sql
