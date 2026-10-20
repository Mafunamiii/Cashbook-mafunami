"""Create the financial-domain schema.

Revision ID: 20260801_0001
Revises:
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260801_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Types are created explicitly once below.  Keeping table-bound enum objects
# from auto-creating avoids duplicate CREATE TYPE statements in offline SQL.
user_role = postgresql.ENUM("user", "admin", name="user_role", create_type=False)
transaction_type = postgresql.ENUM("inflow", "outflow", name="transaction_type", create_type=False)
reporting_mode = postgresql.ENUM(
    "calendar_month", "payday", name="reporting_mode", create_type=False
)


def _timestamps() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    user_role.create(op.get_bind(), checkfirst=True)
    transaction_type.create(op.get_bind(), checkfirst=True)
    reporting_mode.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("csrf_secret_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("ip_address", sa.String(length=45)),
        sa.Column("user_agent", sa.String(length=512)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sessions_user_expires", "sessions", ["user_id", "expires_at"])

    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=False),
        sa.Column("icon", sa.String(length=64)),
        sa.Column("transaction_type", transaction_type, nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "name", "transaction_type", name="uq_categories_user_name_type"
        ),
        sa.UniqueConstraint("user_id", "id", "transaction_type", name="uq_categories_user_id_type"),
        sa.UniqueConstraint("user_id", "id", name="uq_categories_user_id"),
    )
    op.create_index("ix_categories_user_active", "categories", ["user_id", "archived_at"])

    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("transaction_type", transaction_type, nullable=False),
        sa.Column("amount_minor", sa.BIGINT(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint("amount_minor > 0", name="ck_transactions_positive_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "category_id", "transaction_type"],
            ["categories.user_id", "categories.id", "categories.transaction_type"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_transactions_user_date", "transactions", ["user_id", "transaction_date"])
    op.create_index(
        "ix_transactions_user_category_date",
        "transactions",
        ["user_id", "category_id", "transaction_date"],
    )

    op.create_table(
        "budget_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.BIGINT(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM month_start) = 1", name="ck_budget_configurations_month_start"
        ),
        sa.CheckConstraint("amount_minor >= 0", name="ck_budget_configurations_nonnegative_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "month_start", name="uq_budget_configurations_user_month"),
    )
    op.create_index(
        "ix_budget_configurations_user_month", "budget_configurations", ["user_id", "month_start"]
    )

    op.create_table(
        "payday_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_day", sa.Integer(), nullable=False),
        sa.Column("second_day", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.CheckConstraint("first_day BETWEEN 1 AND 31", name="ck_payday_schedules_first_day"),
        sa.CheckConstraint("second_day BETWEEN 1 AND 31", name="ck_payday_schedules_second_day"),
        sa.CheckConstraint("first_day < second_day", name="ck_payday_schedules_ordered_days"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_payday_schedules_user"),
        sa.UniqueConstraint("user_id", "id", name="uq_payday_schedules_user_id"),
    )

    op.create_table(
        "payday_allowances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payday_schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.BIGINT(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("amount_minor >= 0", name="ck_payday_allowances_nonnegative_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "payday_schedule_id"],
            ["payday_schedules.user_id", "payday_schedules.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "payday_schedule_id", "period_start", name="uq_payday_allowances_schedule_period"
        ),
    )
    op.create_index(
        "ix_payday_allowances_user_period", "payday_allowances", ["user_id", "period_start"]
    )

    op.create_table(
        "category_budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.BIGINT(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "EXTRACT(DAY FROM month_start) = 1", name="ck_category_budgets_month_start"
        ),
        sa.CheckConstraint("amount_minor >= 0", name="ck_category_budgets_nonnegative_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id", "category_id", "month_start", name="uq_category_budgets_user_category_month"
        ),
    )
    op.create_index(
        "ix_category_budgets_user_month", "category_budgets", ["user_id", "month_start"]
    )

    op.create_table(
        "user_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False, server_default="PHP"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Manila"),
        sa.Column(
            "reporting_mode", reporting_mode, nullable=False, server_default="calendar_month"
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100)),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("ip_address", sa.String(length=45)),
        sa.Column("user_agent", sa.String(length=512)),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_audit_events_actor_occurred", "audit_events", ["actor_user_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor_occurred", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("user_preferences")
    op.drop_index("ix_category_budgets_user_month", table_name="category_budgets")
    op.drop_table("category_budgets")
    op.drop_index("ix_payday_allowances_user_period", table_name="payday_allowances")
    op.drop_table("payday_allowances")
    op.drop_table("payday_schedules")
    op.drop_index("ix_budget_configurations_user_month", table_name="budget_configurations")
    op.drop_table("budget_configurations")
    op.drop_index("ix_transactions_user_category_date", table_name="transactions")
    op.drop_index("ix_transactions_user_date", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_categories_user_active", table_name="categories")
    op.drop_table("categories")
    op.drop_index("ix_sessions_user_expires", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
    reporting_mode.drop(op.get_bind(), checkfirst=True)
    transaction_type.drop(op.get_bind(), checkfirst=True)
    user_role.drop(op.get_bind(), checkfirst=True)
