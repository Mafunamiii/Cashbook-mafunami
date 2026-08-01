"""Add the user appearance preference.

Revision ID: 20260801_0003
Revises: 20260801_0002
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0003"
down_revision: str | None = "20260801_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

appearance_preference = postgresql.ENUM(
    "system", "dark", "light", name="appearance_preference", create_type=False
)


def upgrade() -> None:
    appearance_preference.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "user_preferences",
        sa.Column(
            "appearance_preference",
            appearance_preference,
            nullable=False,
            server_default="system",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "appearance_preference")
    appearance_preference.drop(op.get_bind(), checkfirst=True)
