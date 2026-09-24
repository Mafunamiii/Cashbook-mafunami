"""Mark transactions that predate transaction-level currency support."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0010"
down_revision: str | None = "20260811_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("legacy_currency_record", sa.Boolean(), nullable=True))
    op.execute("UPDATE transactions SET legacy_currency_record = TRUE")
    op.alter_column(
        "transactions", "legacy_currency_record", nullable=False, server_default=sa.false()
    )


def downgrade() -> None:
    op.drop_column("transactions", "legacy_currency_record")
