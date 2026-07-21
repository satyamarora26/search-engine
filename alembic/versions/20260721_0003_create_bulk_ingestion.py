"""create bulk ingestion schema

Revision ID: 20260721_0003
Revises: 20260721_0002
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260721_0003"
down_revision: str | None = "20260721_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("resource_key", sa.Text(), nullable=True),
    )
    op.execute(
        "update jobs set resource_key = 'search_index' "
        "where job_type = 'search_index_rebuild'"
    )
    op.drop_index(
        "jobs_one_active_search_index_rebuild_idx",
        table_name="jobs",
    )
    op.create_index(
        "jobs_one_active_resource_idx",
        "jobs",
        ["resource_key"],
        unique=True,
        postgresql_where=sa.text(
            "resource_key is not null "
            "and status in ('PENDING', 'STARTED')"
        ),
    )
    op.create_table(
        "ingestion_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("document_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ingestion_items_position_check",
        ),
        sa.CheckConstraint(
            "status in ('pending', 'imported', 'skipped', 'failed')",
            name="ingestion_items_status_check",
        ),
        sa.CheckConstraint(
            "(status = 'pending' and document_id is null and error is null) "
            "or (status = 'imported' and document_id is not null "
            "and error is null) "
            "or (status in ('skipped', 'failed') and document_id is null "
            "and error is not null)",
            name="ingestion_items_outcome_check",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "position",
            name="ingestion_items_job_position_key",
        ),
    )
    op.create_index(
        "ingestion_items_job_status_position_idx",
        "ingestion_items",
        ["job_id", "status", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "ingestion_items_job_status_position_idx",
        table_name="ingestion_items",
    )
    op.drop_table("ingestion_items")
    op.drop_index("jobs_one_active_resource_idx", table_name="jobs")
    op.create_index(
        "jobs_one_active_search_index_rebuild_idx",
        "jobs",
        ["job_type"],
        unique=True,
        postgresql_where=sa.text(
            "job_type = 'search_index_rebuild' "
            "and status in ('PENDING', 'STARTED')"
        ),
    )
    op.drop_column("jobs", "resource_key")
