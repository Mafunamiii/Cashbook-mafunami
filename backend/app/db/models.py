"""Persistence models for the Cashbook financial domain.

All monetary columns use integer minor units.  Application services added in a
later stage will enforce cross-table ownership and category/type consistency.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BIGINT,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TransactionType(str, enum.Enum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


class ReportingMode(str, enum.Enum):
    CALENDAR_MONTH = "calendar_month"
    PAYDAY = "payday"


class AppearancePreference(str, enum.Enum):
    SYSTEM = "system"
    DARK = "dark"
    LIGHT = "light"


def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    """Persist string enum values, matching the lowercase PostgreSQL types."""
    return [str(member.value) for member in enum_class]


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Timestamped, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=enum_values),
        nullable=False,
        default=UserRole.USER,
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(nullable=False, default=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    categories: Mapped[list[Category]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    preferences: Mapped[UserPreferences | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    budget_configurations: Mapped[list[BudgetConfiguration]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    payday_schedules: Mapped[list[PaydaySchedule]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Session(Timestamped, Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    csrf_secret_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="sessions")


class Category(Timestamped, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "name", "transaction_type", name="uq_categories_user_name_type"
        ),
        UniqueConstraint("user_id", "id", "transaction_type", name="uq_categories_user_id_type"),
        UniqueConstraint("user_id", "id", name="uq_categories_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str] = mapped_column(String(32), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(64))
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type", values_callable=enum_values), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    budget_reset_each_payday: Mapped[bool] = mapped_column(nullable=False, default=False)
    budget_reset_anchor: Mapped[date | None] = mapped_column(Date)

    user: Mapped[User] = relationship(back_populates="categories")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="category", foreign_keys="Transaction.category_id"
    )


class Transaction(Timestamped, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_transactions_positive_amount"),
        ForeignKeyConstraint(
            ["user_id", "category_id", "transaction_type"],
            ["categories.user_id", "categories.id", "categories.transaction_type"],
            ondelete="RESTRICT",
        ),
        Index("ix_transactions_user_date", "user_id", "transaction_date"),
        Index("ix_transactions_user_category_date", "user_id", "category_id", "transaction_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(
            TransactionType,
            name="transaction_type",
            create_type=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    amount_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="transactions")
    category: Mapped[Category] = relationship(
        back_populates="transactions", foreign_keys=[category_id]
    )


class BudgetConfiguration(Timestamped, Base):
    __tablename__ = "budget_configurations"
    __table_args__ = (
        UniqueConstraint("user_id", "month_start", name="uq_budget_configurations_user_month"),
        CheckConstraint(
            "EXTRACT(DAY FROM month_start) = 1", name="ck_budget_configurations_month_start"
        ),
        CheckConstraint("amount_minor >= 0", name="ck_budget_configurations_nonnegative_amount"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)

    user: Mapped[User] = relationship(back_populates="budget_configurations")


class PaydaySchedule(Timestamped, Base):
    __tablename__ = "payday_schedules"
    __table_args__ = (
        UniqueConstraint("user_id", "effective_from", name="uq_payday_schedules_user_effective"),
        UniqueConstraint("user_id", "id", name="uq_payday_schedules_user_id"),
        CheckConstraint("first_day BETWEEN 1 AND 31", name="ck_payday_schedules_first_day"),
        CheckConstraint("second_day BETWEEN 1 AND 31", name="ck_payday_schedules_second_day"),
        CheckConstraint("first_day < second_day", name="ck_payday_schedules_ordered_days"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    first_day: Mapped[int] = mapped_column(Integer, nullable=False)
    second_day: Mapped[int] = mapped_column(Integer, nullable=False)
    # A schedule is immutable once it has been used.  Selecting the latest
    # effective schedule for a transaction date preserves historical periods
    # when a user later changes their payday cutoffs.
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="payday_schedules")
    allowances: Mapped[list[PaydayAllowance]] = relationship(back_populates="payday_schedule")


class PaydayAllowance(Timestamped, Base):
    __tablename__ = "payday_allowances"
    __table_args__ = (
        UniqueConstraint(
            "payday_schedule_id", "period_start", name="uq_payday_allowances_schedule_period"
        ),
        CheckConstraint("amount_minor >= 0", name="ck_payday_allowances_nonnegative_amount"),
        ForeignKeyConstraint(
            ["user_id", "payday_schedule_id"],
            ["payday_schedules.user_id", "payday_schedules.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    payday_schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)

    payday_schedule: Mapped[PaydaySchedule] = relationship(back_populates="allowances")


class CategoryBudget(Timestamped, Base):
    __tablename__ = "category_budgets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category_id", "month_start", name="uq_category_budgets_user_category_month"
        ),
        CheckConstraint(
            "EXTRACT(DAY FROM month_start) = 1", name="ck_category_budgets_month_start"
        ),
        CheckConstraint("amount_minor >= 0", name="ck_category_budgets_nonnegative_amount"),
        ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)


class CategoryBudgetResetHistory(Timestamped, Base):
    """Snapshot an allocation before an automatic payday-cycle reset."""

    __tablename__ = "category_budget_reset_history"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "category_id",
            "period_start",
            name="uq_category_budget_reset_history_user_category_period",
        ),
        CheckConstraint(
            "amount_minor >= 0", name="ck_category_budget_reset_history_nonnegative_amount"
        ),
        ForeignKeyConstraint(
            ["user_id", "category_id"],
            ["categories.user_id", "categories.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BIGINT, nullable=False)


class UserPreferences(Timestamped, Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="PHP")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Manila")
    reporting_mode: Mapped[ReportingMode] = mapped_column(
        Enum(ReportingMode, name="reporting_mode", values_callable=enum_values),
        nullable=False,
        default=ReportingMode.CALENDAR_MONTH,
    )
    appearance_preference: Mapped[AppearancePreference] = mapped_column(
        Enum(
            AppearancePreference,
            name="appearance_preference",
            values_callable=enum_values,
        ),
        nullable=False,
        default=AppearancePreference.SYSTEM,
    )
    dashboard_show_inflow: Mapped[bool] = mapped_column(nullable=False, default=True)
    dashboard_show_outflow: Mapped[bool] = mapped_column(nullable=False, default=True)
    dashboard_show_profit_loss: Mapped[bool] = mapped_column(nullable=False, default=True)
    dashboard_show_budget_used: Mapped[bool] = mapped_column(nullable=False, default=True)
    payday_setup_notice_dismissed: Mapped[bool] = mapped_column(nullable=False, default=False)

    user: Mapped[User] = relationship(back_populates="preferences")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_actor_occurred", "actor_user_id", "occurred_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
