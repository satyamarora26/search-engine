from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.job import Job


def test_job_model_uses_durable_job_columns():
    assert Job.__tablename__ == "jobs"
    assert {
        "id",
        "job_type",
        "resource_key",
        "status",
        "progress_current",
        "progress_total",
        "progress_message",
        "result",
        "error",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    } == set(Job.__table__.columns.keys())


def test_job_model_declares_state_progress_and_active_resource_guards():
    constraint_names = {
        constraint.name for constraint in Job.__table__.constraints
    }
    index_names = {index.name for index in Job.__table__.indexes}

    assert "jobs_status_check" in constraint_names
    assert "jobs_progress_current_check" in constraint_names
    assert "jobs_progress_total_check" in constraint_names
    assert "jobs_progress_bounds_check" in constraint_names
    assert "jobs_one_active_resource_idx" in index_names
    assert "jobs_one_active_search_index_rebuild_idx" not in index_names


def test_job_model_compiles_postgresql_uuid_jsonb_and_timestamps():
    sql = str(
        CreateTable(Job.__table__).compile(dialect=postgresql.dialect())
    )

    assert "CREATE TABLE jobs" in sql
    assert "UUID NOT NULL" in sql
    assert "JSONB" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
