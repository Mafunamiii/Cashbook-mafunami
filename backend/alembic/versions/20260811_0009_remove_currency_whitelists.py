"""Remove obsolete PHP/AED database currency constraints.

Revision ID: 20260811_0009
Revises: 20260811_0008
"""

from alembic import op

revision = "20260811_0009"
down_revision = "20260811_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_transactions_supported_currency", "transactions", type_="check")
    op.drop_constraint("ck_transactions_supported_base_currency", "transactions", type_="check")
    op.drop_constraint(
        "ck_exchange_rate_cache_supported_source_currency", "exchange_rate_cache", type_="check"
    )
    op.drop_constraint(
        "ck_exchange_rate_cache_supported_target_currency", "exchange_rate_cache", type_="check"
    )


def downgrade() -> None:
    # A downgrade cannot safely restore a PHP/AED restriction after generic
    # currency data may have been written.
    raise RuntimeError("Downgrade is unsafe after generic currency data exists.")
