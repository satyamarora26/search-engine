"""create jobs table

Revision ID: 20260721_0002
Revises: 20260720_0001
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260721_0002"
down_revision: str | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column(
            "progress_current",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("progress_total", sa.BigInteger(), nullable=True),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('PENDING', 'STARTED', 'SUCCESS', 'FAILURE')",
            name="jobs_status_check",
        ),
        sa.CheckConstraint(
            "progress_current >= 0",
            name="jobs_progress_current_check",
        ),
        sa.CheckConstraint(
            "progress_total is null or progress_total > 0",
            name="jobs_progress_total_check",
        ),
        sa.CheckConstraint(
            "progress_total is null or progress_current <= progress_total",
            name="jobs_progress_bounds_check",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "jobs_status_created_at_idx",
        "jobs",
        ["status", "created_at"],
    )
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


def downgrade() -> None:
    op.drop_index(
        "jobs_one_active_search_index_rebuild_idx",
        table_name="jobs",
    )
    op.drop_index("jobs_status_created_at_idx", table_name="jobs")
    op.drop_table("jobs")
