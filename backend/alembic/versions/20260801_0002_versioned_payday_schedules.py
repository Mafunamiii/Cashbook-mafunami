"""Preserve historical payday cutoffs with immutable schedule versions.

Revision ID: 20260801_0002
Revises: 20260801_0001
Create Date: 2026-08-01
"""

import sqlalchemy as sa

from alembic import op

revision = "20260801_0002"
down_revision = "20260801_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing installations had one schedule per user.  Treat it as having
    # applied since the beginning of the supported Gregorian date range so all
    # historical allowance references remain valid.
    op.add_column(
        "payday_schedules",
        sa.Column("effective_from", sa.Date(), nullable=True),
    )
    op.execute("UPDATE payday_schedules SET effective_from = DATE '0001-01-01'")
    op.alter_column("payday_schedules", "effective_from", nullable=False)
    op.drop_constraint("uq_payday_schedules_user", "payday_schedules", type_="unique")
    op.create_unique_constraint(
        "uq_payday_schedules_user_effective",
        "payday_schedules",
        ["user_id", "effective_from"],
    )
    op.create_index(
        "ix_payday_schedules_user_effective",
        "payday_schedules",
        ["user_id", "effective_from"],
    )


def downgrade() -> None:
    op.drop_index("ix_payday_schedules_user_effective", table_name="payday_schedules")
    op.drop_constraint(
        "uq_payday_schedules_user_effective", "payday_schedules", type_="unique"
    )
    op.create_unique_constraint("uq_payday_schedules_user", "payday_schedules", ["user_id"])
    op.drop_column("payday_schedules", "effective_from")
