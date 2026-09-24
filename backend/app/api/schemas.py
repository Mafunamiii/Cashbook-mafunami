from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import AppearancePreference, ReportingMode, TransactionType, UserRole
from app.domain.currency import currency_metadata, normalize_currency_code


class RegistrationRequest(BaseModel):
    email: str = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=256)
    currency_code: str
    invite_code: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.count("@") != 1 or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        currency = normalize_currency_code(value)
        currency_metadata(currency)
        return currency


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class TemporaryPasswordRequest(BaseModel):
    temporary_password: str = Field(min_length=8, max_length=256)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: UserRole
    must_change_password: bool


class AuthenticatedResponse(BaseModel):
    user: UserResponse
    csrf_token: str


class RecoveryInfoResponse(BaseModel):
    message: str


class DashboardSummaryPreferences(BaseModel):
    inflow: bool = True
    outflow: bool = True
    profit_loss: bool = True
    budget_used: bool = True


class SettingsResponse(BaseModel):
    display_name: str
    email: str
    currency_code: str
    reporting_mode: ReportingMode
    appearance_preference: AppearancePreference
    dashboard_summary: DashboardSummaryPreferences
    payday_setup_notice_dismissed: bool
    has_financial_data: bool = False


class CurrencyResponse(BaseModel):
    code: str
    name: str
    minor_unit: int = Field(ge=0, le=3)


class SettingsUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    currency_code: str | None = None
    appearance_preference: AppearancePreference | None = None
    dashboard_summary: DashboardSummaryPreferences | None = None
    payday_setup_notice_dismissed: bool | None = None

    @field_validator("display_name")
    @classmethod
    def display_name_cannot_be_whitespace(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Display name cannot be blank.")
        return value

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_currency_code(value)


class AdminUserResponse(BaseModel):
    """Account-management fields only; never includes financial data or secrets."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    must_change_password: bool
    created_at: datetime


class LegacyCurrencyMigrationRequest(BaseModel):
    currency_code: str
    confirmation: Literal["MIGRATE LEGACY CURRENCY"]

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        currency = normalize_currency_code(value)
        currency_metadata(currency)
        return currency


class LegacyCurrencyMigrationResponse(BaseModel):
    user_id: uuid.UUID
    previous_currency_code: str
    currency_code: str
    legacy_transactions_migrated: int


class AccountStatusUpdateRequest(BaseModel):
    is_active: bool


class TemporaryPasswordResponse(BaseModel):
    """Shown to the administrator exactly once; it is never persisted in plaintext."""

    temporary_password: str


class DebugSeedResponse(BaseModel):
    """Summary of demo records added to the requesting administrator's account."""

    transactions_created: int
    budgets_created: int
    category_budgets_created: int


class DebugCycleSeedResponse(DebugSeedResponse):
    """Summary of completed payday-cycle demo records added to the caller."""

    schedules_created: int
    allowances_created: int


class DebugClearResponse(BaseModel):
    transactions_deleted: int
    budgets_deleted: int
    category_budgets_deleted: int
    allowances_deleted: int
    schedules_deleted: int


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    color: str
    icon: str | None
    transaction_type: TransactionType
    archived_at: datetime | None


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(min_length=7, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str | None = Field(default=None, max_length=64)
    transaction_type: TransactionType


class CategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(
        default=None, min_length=7, max_length=7, pattern=r"^#[0-9a-fA-F]{6}$"
    )
    icon: str | None = Field(default=None, max_length=64)


class TransactionResponse(BaseModel):
    """A transaction plus the presentation fields of its owned category."""

    id: uuid.UUID
    name: str
    transaction_type: TransactionType
    category_id: uuid.UUID
    category_name: str
    category_color: str
    amount_minor: int
    currency_code: str
    base_amount_minor: int
    base_currency_code: str
    exchange_rate: Decimal
    exchange_rate_date: date
    exchange_rate_source: str
    transaction_date: date
    notes: str | None
    created_at: datetime
    updated_at: datetime


class TransactionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    transaction_type: TransactionType
    category_id: uuid.UUID
    amount_minor: int = Field(ge=1, le=9_223_372_036_854_775_807)
    currency_code: str | None = None
    transaction_date: date = Field(default_factory=date.today)
    notes: str | None = Field(default=None, max_length=10_000)

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return normalize_currency_code(value) if value is not None else None


class TransactionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    transaction_type: TransactionType | None = None
    category_id: uuid.UUID | None = None
    amount_minor: int | None = Field(default=None, ge=1, le=9_223_372_036_854_775_807)
    currency_code: str | None = None
    transaction_date: date | None = None
    notes: str | None = Field(default=None, max_length=10_000)

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return normalize_currency_code(value) if value is not None else None


class TransactionPageResponse(BaseModel):
    items: list[StatementTransactionResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: Literal["newest", "oldest"]


class TransactionDeletionResponse(BaseModel):
    transactions_deleted: int


class TransactionBulkDeleteRequest(BaseModel):
    transaction_ids: list[uuid.UUID] = Field(min_length=1, max_length=1_000)


class StatementTransactionResponse(TransactionResponse):
    """A transaction row enriched for the statement presentation.

    ``running_balance_minor`` is the user's cumulative net cash flow through
    this transaction, calculated in chronological transaction order before
    any statement filters or display sorting are applied.
    """

    running_balance_minor: int
    period_start: date | None = None
    period_end: date | None = None


class BudgetUpdateRequest(BaseModel):
    amount_minor: int = Field(ge=0, le=9_223_372_036_854_775_807)


class ReportingModeUpdateRequest(BaseModel):
    reporting_mode: ReportingMode


class PaydayScheduleCreateRequest(BaseModel):
    first_day: int = Field(ge=1, le=31)
    second_day: int = Field(ge=1, le=31)
    effective_from: date


class PaydayAllowanceUpdateRequest(BaseModel):
    amount_minor: int = Field(ge=0, le=9_223_372_036_854_775_807)


class CategoryBudgetUpdateRequest(BaseModel):
    amount_minor: int | None = Field(..., ge=0, le=9_223_372_036_854_775_807)
    reset_each_payday: bool | None = None


class PaydayScheduleResponse(BaseModel):
    id: uuid.UUID
    first_day: int
    second_day: int
    effective_from: date
    is_active: bool


class BudgetAllocationResponse(BaseModel):
    amount_minor: int | None
    used_minor: int
    remaining_minor: int | None
    usage_percent: str | None
    is_overspent: bool


class PaydayAllowanceResponse(BudgetAllocationResponse):
    period_start: date
    period_end: date


class CategoryBudgetResponse(BudgetAllocationResponse):
    category_id: uuid.UUID
    category_name: str
    category_color: str
    reset_each_payday: bool


class BudgetCycleResponse(BudgetAllocationResponse):
    base_currency_code: str
    month_start: date
    month_end: date
    total_inflow_minor: int
    total_outflow_minor: int
    net_profit_loss_minor: int
    reporting_mode: ReportingMode
    payday_schedule: PaydayScheduleResponse | None
    payday_allowances: list[PaydayAllowanceResponse]
    allowances_total_minor: int
    allowances_match_budget: bool | None
    category_budgets: list[CategoryBudgetResponse]


class BudgetSettingsResponse(BaseModel):
    reporting_mode: ReportingMode
    payday_schedule: PaydayScheduleResponse | None


class DashboardCategoryResponse(BudgetAllocationResponse):
    category_id: uuid.UUID
    category_name: str
    category_color: str


class DashboardTransactionResponse(TransactionResponse):
    """Recent owner-scoped activity shown on the dashboard."""


class DashboardResponse(BudgetAllocationResponse):
    base_currency_code: str
    period_start: date
    period_end: date
    period_mode: ReportingMode
    period_label: str
    total_inflow_minor: int
    total_outflow_minor: int
    net_profit_loss_minor: int
    payday_schedule: PaydayScheduleResponse | None
    payday_is_configured: bool
    payday_is_enabled: bool
    category_spending: list[DashboardCategoryResponse]
    category_budgets: list[DashboardCategoryResponse]
    recent_transactions: list[DashboardTransactionResponse]
