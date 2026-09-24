"""Add immutable base-currency conversion metadata to transactions.

Revision ID: 20260811_0007
Revises: 20260803_0006
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260811_0007"
down_revision: str | None = "20260803_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("currency_code", sa.String(length=3), nullable=False, server_default="PHP"),
    )
    op.add_column("transactions", sa.Column("base_amount_minor", sa.BigInteger(), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("base_currency_code", sa.String(length=3), nullable=False, server_default="PHP"),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "exchange_rate",
            sa.Numeric(precision=20, scale=10),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column("transactions", sa.Column("exchange_rate_date", sa.Date(), nullable=True))
    op.add_column(
        "transactions",
        sa.Column(
            "exchange_rate_source", sa.String(length=32), nullable=False, server_default="identity"
        ),
    )
    op.execute(
        "UPDATE transactions "
        "SET base_amount_minor = amount_minor, exchange_rate_date = transaction_date"
    )
    op.alter_column("transactions", "base_amount_minor", nullable=False)
    op.alter_column("transactions", "exchange_rate_date", nullable=False)
    op.create_check_constraint(
        "ck_transactions_supported_currency", "transactions", "currency_code IN ('PHP', 'AED')"
    )
    op.create_check_constraint(
        "ck_transactions_supported_base_currency",
        "transactions",
        "base_currency_code IN ('PHP', 'AED')",
    )
    op.create_check_constraint(
        "ck_transactions_positive_exchange_rate", "transactions", "exchange_rate > 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_positive_exchange_rate", "transactions", type_="check")
    op.drop_constraint("ck_transactions_supported_base_currency", "transactions", type_="check")
    op.drop_constraint("ck_transactions_supported_currency", "transactions", type_="check")
    op.drop_column("transactions", "exchange_rate_source")
    op.drop_column("transactions", "exchange_rate_date")
    op.drop_column("transactions", "exchange_rate")
    op.drop_column("transactions", "base_currency_code")
    op.drop_column("transactions", "base_amount_minor")
    op.drop_column("transactions", "currency_code")
