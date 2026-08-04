"""Add persistent dashboard summary preferences.

Revision ID: 20260803_0004
Revises: 20260801_0003
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260803_0004"
down_revision: str | None = "20260801_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column_name in (
        "dashboard_show_inflow",
        "dashboard_show_outflow",
        "dashboard_show_profit_loss",
        "dashboard_show_budget_used",
    ):
        op.add_column(
            "user_preferences",
            sa.Column(column_name, sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    for column_name in (
        "dashboard_show_budget_used",
        "dashboard_show_profit_loss",
        "dashboard_show_outflow",
        "dashboard_show_inflow",
    ):
        op.drop_column("user_preferences", column_name)
