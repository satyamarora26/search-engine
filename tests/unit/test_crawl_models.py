from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.crawl import CrawlFrontier, CrawlItem, CrawlRun


def constraint_names(model):
    return {constraint.name for constraint in model.__table__.constraints}


def index_names(model):
    return {index.name for index in model.__table__.indexes}


def compile_table(model):
    return str(
        CreateTable(model.__table__).compile(dialect=postgresql.dialect())
    )


def test_generic_crawl_run_has_source_and_request_columns():
    assert {
        "job_id",
        "source_key",
        "seed_url",
        "max_articles",
        "max_depth",
        "discovery_complete",
        "limit_reached",
        "created_at",
        "updated_at",
    } == set(CrawlRun.__table__.columns.keys())


def test_generic_frontier_has_locator_and_continuation_columns():
    assert {
        "id",
        "job_id",
        "locator",
        "depth",
        "continuation",
        "status",
        "error",
        "created_at",
        "updated_at",
    } == set(CrawlFrontier.__table__.columns.keys())
    assert CrawlFrontier.__table__.c.continuation.type.none_as_null is True


def test_generic_item_has_source_neutral_fetch_and_ingestion_columns():
    assert {
        "id",
        "job_id",
        "position",
        "source_item_id",
        "discovered_url",
        "canonical_url",
        "title",
        "embedded_content",
        "fetch_status",
        "fetch_attempts",
        "ingestion_item_id",
        "error",
        "fetched_at",
        "created_at",
        "updated_at",
    } == set(CrawlItem.__table__.columns.keys())


def test_generic_crawler_models_declare_named_constraints_and_indexes():
    assert {
        "crawl_runs_article_limit_check",
        "crawl_runs_depth_check",
    } <= constraint_names(CrawlRun)
    assert {
        "crawl_frontier_job_locator_key",
        "crawl_frontier_depth_check",
        "crawl_frontier_status_check",
        "crawl_frontier_outcome_check",
    } <= constraint_names(CrawlFrontier)
    assert {
        "crawl_items_job_position_key",
        "crawl_items_job_canonical_key",
        "crawl_items_position_check",
        "crawl_items_attempts_check",
        "crawl_items_status_check",
        "crawl_items_outcome_check",
        "crawl_items_ingestion_item_key",
    } <= constraint_names(CrawlItem)
    assert index_names(CrawlFrontier) == {
        "crawl_frontier_job_status_depth_idx"
    }
    assert index_names(CrawlItem) == {
        "crawl_items_job_status_position_idx"
    }


def test_generic_models_compile_postgresql_types_and_foreign_keys():
    run_sql = compile_table(CrawlRun)
    frontier_sql = compile_table(CrawlFrontier)
    item_sql = compile_table(CrawlItem)

    assert "FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE" in run_sql
    assert (
        "FOREIGN KEY(job_id) REFERENCES crawl_runs (job_id) ON DELETE CASCADE"
        in frontier_sql
    )
    assert "JSON" in frontier_sql
    assert "JSONB" not in frontier_sql
    assert (
        "FOREIGN KEY(job_id) REFERENCES crawl_runs (job_id) ON DELETE CASCADE"
        in item_sql
    )
    assert (
        "FOREIGN KEY(ingestion_item_id) REFERENCES ingestion_items (id) "
        "ON DELETE CASCADE"
        in item_sql
    )
    assert "TIMESTAMP WITH TIME ZONE" in item_sql
