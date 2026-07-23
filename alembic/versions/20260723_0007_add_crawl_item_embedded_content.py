"""store source-provided crawl item content

Revision ID: 20260723_0007
Revises: 20260723_0006
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0007"
down_revision: str | None = "20260723_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crawl_items",
        sa.Column("embedded_content", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crawl_items", "embedded_content")
