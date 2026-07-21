from importlib import import_module

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.document import Document
from app.models.job import Job


def get_ingestion_item_model():
    return import_module("app.models.ingestion_item").IngestionItem


def test_ingestion_item_model_has_durable_payload_outcome_columns():
    ingestion_item = get_ingestion_item_model()

    assert ingestion_item.__tablename__ == "ingestion_items"
    assert {
        "id",
        "job_id",
        "position",
        "payload",
        "status",
        "document_id",
        "error",
        "created_at",
        "updated_at",
    } == set(ingestion_item.__table__.columns.keys())


def test_ingestion_item_model_declares_constraints_and_indexes():
    ingestion_item = get_ingestion_item_model()
    constraint_names = {
        constraint.name for constraint in ingestion_item.__table__.constraints
    }
    index_names = {index.name for index in ingestion_item.__table__.indexes}

    assert "ingestion_items_job_position_key" in constraint_names
    assert "ingestion_items_position_check" in constraint_names
    assert "ingestion_items_status_check" in constraint_names
    assert "ingestion_items_outcome_check" in constraint_names
    assert "ingestion_items_job_status_position_idx" in index_names


def test_ingestion_item_model_compiles_postgresql_json_and_foreign_keys():
    ingestion_item = get_ingestion_item_model()
    sql = str(
        CreateTable(ingestion_item.__table__).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "CREATE TABLE ingestion_items" in sql
    assert "JSON NOT NULL" in sql
    assert "JSONB NOT NULL" not in sql
    assert "FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE" in sql
    assert "FOREIGN KEY(document_id) REFERENCES documents (id)" in sql
