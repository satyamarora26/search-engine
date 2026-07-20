from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.document import Document


def test_document_model_uses_documents_table():
    column_names = set(Document.__table__.columns.keys())

    assert Document.__tablename__ == "documents"
    assert {
        "id",
        "title",
        "url",
        "content",
        "status",
        "created_at",
        "updated_at",
    } <= column_names


def test_document_model_has_expected_constraints_and_indexes():
    constraint_names = {constraint.name for constraint in Document.__table__.constraints}
    index_names = {index.name for index in Document.__table__.indexes}

    assert "documents_url_key" in constraint_names
    assert "documents_status_check" in constraint_names
    assert "documents_status_created_at_idx" in index_names
    assert "documents_active_url_idx" in index_names


def test_document_model_compiles_for_postgresql():
    sql = str(CreateTable(Document.__table__).compile(dialect=postgresql.dialect()))

    assert "CREATE TABLE documents" in sql
    assert "BIGINT" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
