"""create Wikipedia crawler schema

Revision ID: 20260721_0005
Revises: 20260721_0004
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260721_0005"
down_revision: str | None = "20260721_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wikipedia_crawl_runs",
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("root_category", sa.Text(), nullable=False),
        sa.Column("max_articles", sa.Integer(), nullable=False),
        sa.Column("max_depth", sa.SmallInteger(), nullable=False),
        sa.Column(
            "discovery_complete",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "category_limit_reached",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
            "max_articles between 1 and 500",
            name="wikipedia_crawl_runs_article_limit_check",
        ),
        sa.CheckConstraint(
            "max_depth between 0 and 2",
            name="wikipedia_crawl_runs_depth_check",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_table(
        "wikipedia_crawl_frontier",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("category_title", sa.Text(), nullable=False),
        sa.Column("depth", sa.SmallInteger(), nullable=False),
        sa.Column(
            "continuation",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            server_default="pending",
            nullable=False,
        ),
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
            "depth between 0 and 2",
            name="wikipedia_crawl_frontier_depth_check",
        ),
        sa.CheckConstraint(
            "status in ('pending', 'completed', 'failed')",
            name="wikipedia_crawl_frontier_status_check",
        ),
        sa.CheckConstraint(
            "(status = 'pending' and error is null) or "
            "(status = 'completed' and continuation is null "
            "and error is null) or "
            "(status = 'failed' and error is not null)",
            name="wikipedia_crawl_frontier_outcome_check",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["wikipedia_crawl_runs.job_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "category_title",
            name="wikipedia_crawl_frontier_job_category_key",
        ),
    )
    op.create_index(
        "wikipedia_crawl_frontier_job_status_depth_idx",
        "wikipedia_crawl_frontier",
        ["job_id", "status", "depth", "id"],
    )
    op.create_table(
        "wikipedia_crawl_pages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("wikipedia_page_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column(
            "fetch_status",
            sa.Text(),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "fetch_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("ingestion_item_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
            name="wikipedia_crawl_pages_position_check",
        ),
        sa.CheckConstraint(
            "fetch_attempts >= 0",
            name="wikipedia_crawl_pages_attempts_check",
        ),
        sa.CheckConstraint(
            "fetch_status in ('pending', 'fetched', 'failed')",
            name="wikipedia_crawl_pages_status_check",
        ),
        sa.CheckConstraint(
            "(fetch_status = 'pending' and ingestion_item_id is null "
            "and error is null and fetched_at is null) or "
            "(fetch_status = 'fetched' and ingestion_item_id is not null "
            "and error is null and fetched_at is not null) or "
            "(fetch_status = 'failed' and ingestion_item_id is null "
            "and error is not null and fetched_at is null)",
            name="wikipedia_crawl_pages_outcome_check",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["wikipedia_crawl_runs.job_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_item_id"],
            ["ingestion_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "position",
            name="wikipedia_crawl_pages_job_position_key",
        ),
        sa.UniqueConstraint(
            "job_id",
            "wikipedia_page_id",
            name="wikipedia_crawl_pages_job_page_key",
        ),
        sa.UniqueConstraint(
            "ingestion_item_id",
            name="wikipedia_crawl_pages_ingestion_item_key",
        ),
    )
    op.create_index(
        "wikipedia_crawl_pages_job_status_position_idx",
        "wikipedia_crawl_pages",
        ["job_id", "fetch_status", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "wikipedia_crawl_pages_job_status_position_idx",
        table_name="wikipedia_crawl_pages",
    )
    op.drop_table("wikipedia_crawl_pages")
    op.drop_index(
        "wikipedia_crawl_frontier_job_status_depth_idx",
        table_name="wikipedia_crawl_frontier",
    )
    op.drop_table("wikipedia_crawl_frontier")
    op.drop_table("wikipedia_crawl_runs")
