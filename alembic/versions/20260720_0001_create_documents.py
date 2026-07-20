"""create documents table

Revision ID: 20260720_0001
Revises:
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260720_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
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
            "status in ('active', 'deleted')",
            name="documents_status_check",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="documents_url_key"),
    )
    op.create_index(
        "documents_status_created_at_idx",
        "documents",
        ["status", "created_at"],
    )
    op.create_index(
        "documents_active_url_idx",
        "documents",
        ["url"],
        postgresql_where=sa.text("status = 'active' and url is not null"),
    )


def downgrade() -> None:
    op.drop_index("documents_active_url_idx", table_name="documents")
    op.drop_index("documents_status_created_at_idx", table_name="documents")
    op.drop_table("documents")
