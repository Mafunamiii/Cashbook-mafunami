"""Add persistent shared cache for historical exchange-rate observations.

Revision ID: 20260811_0008
Revises: 20260811_0007
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260811_0008"
down_revision: str | None = "20260811_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchange_rate_cache",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_currency_code", sa.String(length=3), nullable=False),
        sa.Column("target_currency_code", sa.String(length=3), nullable=False),
        sa.Column("requested_date", sa.Date(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=20, scale=10), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint("rate > 0", name="ck_exchange_rate_cache_positive_rate"),
        sa.CheckConstraint(
            "source_currency_code IN ('PHP', 'AED')",
            name="ck_exchange_rate_cache_supported_source_currency",
        ),
        sa.CheckConstraint(
            "target_currency_code IN ('PHP', 'AED')",
            name="ck_exchange_rate_cache_supported_target_currency",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "source_currency_code",
            "target_currency_code",
            "requested_date",
            name="uq_exchange_rate_cache_source_pair_requested_date",
        ),
    )


def downgrade() -> None:
    op.drop_table("exchange_rate_cache")
