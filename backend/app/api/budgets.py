"""Owner-scoped budget configuration and budget-cycle summaries."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.dependencies import ActiveUser, CsrfProtectedUser, DatabaseSession
from app.api.schemas import (
    BudgetAllocationResponse,
    BudgetCycleResponse,
    BudgetSettingsResponse,
    BudgetUpdateRequest,
    CategoryBudgetResponse,
    CategoryBudgetUpdateRequest,
    DashboardCategoryResponse,
    DashboardResponse,
    DashboardTransactionResponse,
    PaydayAllowanceResponse,
    PaydayAllowanceUpdateRequest,
    PaydayScheduleCreateRequest,
    PaydayScheduleResponse,
    ReportingModeUpdateRequest,
)
from app.db.models import (
    AuditEvent,
    BudgetConfiguration,
    Category,
    CategoryBudget,
    PaydayAllowance,
    PaydaySchedule,
    ReportingMode,
    Transaction,
    TransactionType,
    User,
    UserPreferences,
)
from app.domain.financials import (
    CashFlowType,
    FinancialEntry,
    allowance_total_matches_budget,
    calculate_budget_allocation,
    calculate_financial_summary,
)
from app.domain.periods import (
    ReportingPeriod,
    calendar_month_period,
    payday_period,
    payday_periods_starting_in_month,
    versioned_payday_period,
)

router = APIRouter(prefix="/api/v1", tags=["budgets"])


def _month_start_or_422(value: date) -> date:
    if value.day != 1:
        raise HTTPException(status_code=422, detail="month_start must be the first day of a month.")
    return value


def _entries(transactions: list[Transaction]) -> list[FinancialEntry]:
    return [
        FinancialEntry(CashFlowType(transaction.transaction_type.value), transaction.amount_minor)
        for transaction in transactions
    ]


def _decimal_string(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _allocation_response(summary) -> BudgetAllocationResponse:
    return BudgetAllocationResponse(
        amount_minor=summary.allocation_minor,
        used_minor=summary.used_minor,
        remaining_minor=summary.remaining_minor,
        usage_percent=_decimal_string(summary.usage_percent),
        is_overspent=summary.is_overspent,
    )


def _schedule_response(schedule: PaydaySchedule | None) -> PaydayScheduleResponse | None:
    if schedule is None:
        return None
    return PaydayScheduleResponse(
        id=schedule.id,
        first_day=schedule.first_day,
        second_day=schedule.second_day,
        effective_from=schedule.effective_from,
        is_active=schedule.is_active,
    )


def _schedule_for_date(
    db: DatabaseSession, *, user_id: uuid.UUID, value: date
) -> PaydaySchedule | None:
    """Get the immutable schedule version in effect at a particular date."""
    return db.scalar(
        select(PaydaySchedule)
        .where(PaydaySchedule.user_id == user_id, PaydaySchedule.effective_from <= value)
        .order_by(PaydaySchedule.effective_from.desc())
    )


def _schedule_versions(schedules: list[PaydaySchedule]) -> list[tuple[date, int, int]]:
    return [(item.effective_from, item.first_day, item.second_day) for item in schedules]


def _payday_periods_for_month(
    db: DatabaseSession, *, user_id: uuid.UUID, month_start: date
) -> list[tuple[PaydaySchedule, ReportingPeriod]]:
    """Resolve each calendar-month segment using its immutable schedule version.

    A schedule is selected by a period's *start*, never by the end of the
    month being displayed.  That preserves completed segments when a later
    cutoff configuration takes effect.  It also makes a schedule change in a
    month deterministic without rewriting an earlier allowance.
    """
    month = calendar_month_period(month_start)
    schedules = list(
        db.scalars(
            select(PaydaySchedule)
            .where(PaydaySchedule.user_id == user_id)
            .order_by(PaydaySchedule.effective_from.asc())
        )
    )
    periods: list[tuple[PaydaySchedule, ReportingPeriod]] = []
    seen_starts: set[date] = set()
    for schedule in schedules:
        if schedule.effective_from > month.end:
            continue
        for period in payday_periods_starting_in_month(
            month_start, schedule.first_day, schedule.second_day
        ):
            active_schedule = _schedule_for_date(db, user_id=user_id, value=period.start)
            if active_schedule is None or active_schedule.id != schedule.id:
                continue
            period = versioned_payday_period(period.start, _schedule_versions(schedules))
            if period.start not in seen_starts:
                periods.append((schedule, period))
                seen_starts.add(period.start)
    return sorted(periods, key=lambda item: item[1].start)


def _owned_outflow_category_or_422(
    db: DatabaseSession, *, user_id: uuid.UUID, category_id: uuid.UUID
) -> Category:
    category = db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.user_id == user_id,
            Category.transaction_type == TransactionType.OUTFLOW,
        )
    )
    if category is None:
        raise HTTPException(
            status_code=422, detail="Choose an owned outflow category for a category budget."
        )
    return category


def _audit(
    db: DatabaseSession, event_type: str, user: User, request: Request, resource_id=None
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            subject_user_id=user.id,
            event_type=event_type,
            resource_type="budget_configuration",
            resource_id=resource_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )


def _transaction_response(transaction: Transaction) -> DashboardTransactionResponse:
    return DashboardTransactionResponse(
        id=transaction.id,
        name=transaction.name,
        transaction_type=transaction.transaction_type,
        category_id=transaction.category_id,
        category_name=transaction.category.name,
        category_color=transaction.category.color,
        amount_minor=transaction.amount_minor,
        transaction_date=transaction.transaction_date,
        notes=transaction.notes,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
    )


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    current_user: ActiveUser,
    db: DatabaseSession,
    anchor_date: date | None = None,
    period_mode: ReportingMode | None = None,
) -> DashboardResponse:
    """Return a compact, owner-scoped dashboard snapshot for one reporting period."""
    anchor = anchor_date or date.today()
    preferences = db.get(UserPreferences, current_user.id)
    requested_mode = period_mode or (
        preferences.reporting_mode if preferences else ReportingMode.CALENDAR_MONTH
    )
    schedule = _schedule_for_date(db, user_id=current_user.id, value=anchor)
    payday_is_configured = schedule is not None

    if requested_mode == ReportingMode.PAYDAY and schedule is not None:
        schedules = list(
            db.scalars(
                select(PaydaySchedule)
                .where(PaydaySchedule.user_id == current_user.id)
                .order_by(PaydaySchedule.effective_from.asc())
            )
        )
        period = versioned_payday_period(anchor, _schedule_versions(schedules))
        allocation = db.scalar(
            select(PaydayAllowance).where(
                PaydayAllowance.user_id == current_user.id,
                PaydayAllowance.payday_schedule_id == schedule.id,
                PaydayAllowance.period_start == period.start,
            )
        )
        budget_minor = allocation.amount_minor if allocation else None
        resolved_mode = ReportingMode.PAYDAY
        period_label = f"Payday period {period.start:%d %b}–{period.end:%d %b %Y}"
    else:
        period = calendar_month_period(anchor)
        monthly_budget = db.scalar(
            select(BudgetConfiguration).where(
                BudgetConfiguration.user_id == current_user.id,
                BudgetConfiguration.month_start == period.start,
            )
        )
        budget_minor = monthly_budget.amount_minor if monthly_budget else None
        resolved_mode = ReportingMode.CALENDAR_MONTH
        period_label = period.start.strftime("%B %Y")

    transactions = list(
        db.scalars(
            select(Transaction)
            .where(
                Transaction.user_id == current_user.id,
                Transaction.transaction_date >= period.start,
                Transaction.transaction_date <= period.end,
            )
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        )
    )
    summary = calculate_financial_summary(_entries(transactions), budget_minor)
    spending: dict[uuid.UUID, list[Transaction]] = {}
    for transaction in transactions:
        if transaction.transaction_type == TransactionType.OUTFLOW:
            spending.setdefault(transaction.category_id, []).append(transaction)
    category_spending = [
        DashboardCategoryResponse(
            category_id=items[0].category_id,
            category_name=items[0].category.name,
            category_color=items[0].category.color,
            **_allocation_response(calculate_budget_allocation(_entries(items), None)).model_dump(),
        )
        for items in spending.values()
    ]
    category_spending.sort(key=lambda item: item.used_minor, reverse=True)

    category_month = calendar_month_period(period.start).start
    category_configs = {
        item.category_id: item.amount_minor
        for item in db.scalars(
            select(CategoryBudget).where(
                CategoryBudget.user_id == current_user.id,
                CategoryBudget.month_start == category_month,
            )
        )
    }
    category_budgets = [
        DashboardCategoryResponse(
            category_id=items[0].category_id,
            category_name=items[0].category.name,
            category_color=items[0].category.color,
            **_allocation_response(
                calculate_budget_allocation(_entries(items), category_configs[items[0].category_id])
            ).model_dump(),
        )
        for items in spending.values()
        if items[0].category_id in category_configs
    ]
    category_budgets.sort(key=lambda item: item.used_minor, reverse=True)
    recent_transactions = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.user_id == current_user.id)
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .limit(5)
        )
    )
    return DashboardResponse(
        amount_minor=summary.budget_minor,
        used_minor=summary.budget_used_minor,
        remaining_minor=summary.budget_remaining_minor,
        usage_percent=_decimal_string(summary.budget_usage_percent),
        is_overspent=summary.budget_remaining_minor is not None
        and summary.budget_remaining_minor < 0,
        period_start=period.start,
        period_end=period.end,
        period_mode=resolved_mode,
        period_label=period_label,
        total_inflow_minor=summary.total_inflow_minor,
        total_outflow_minor=summary.total_outflow_minor,
        net_profit_loss_minor=summary.net_profit_loss_minor,
        payday_schedule=_schedule_response(schedule),
        payday_is_configured=payday_is_configured,
        category_spending=category_spending,
        category_budgets=category_budgets,
        recent_transactions=[_transaction_response(item) for item in recent_transactions],
    )


@router.get("/budget-settings", response_model=BudgetSettingsResponse)
def get_budget_settings(current_user: ActiveUser, db: DatabaseSession) -> BudgetSettingsResponse:
    preferences = db.get(UserPreferences, current_user.id)
    # Registration creates preferences, but retaining this defensive fallback
    # keeps a migrated account usable.
    reporting_mode = preferences.reporting_mode if preferences else "calendar_month"
    schedule = _schedule_for_date(db, user_id=current_user.id, value=date.today())
    return BudgetSettingsResponse(
        reporting_mode=reporting_mode, payday_schedule=_schedule_response(schedule)
    )


@router.put("/budget-settings", response_model=BudgetSettingsResponse)
def update_reporting_mode(
    payload: ReportingModeUpdateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> BudgetSettingsResponse:
    preferences = db.get(UserPreferences, current_user.id)
    if preferences is None:
        preferences = UserPreferences(
            user_id=current_user.id, reporting_mode=payload.reporting_mode
        )
        db.add(preferences)
    else:
        preferences.reporting_mode = payload.reporting_mode
    _audit(db, "budget.reporting_mode_updated", current_user, request)
    db.commit()
    schedule = _schedule_for_date(db, user_id=current_user.id, value=date.today())
    return BudgetSettingsResponse(
        reporting_mode=preferences.reporting_mode, payday_schedule=_schedule_response(schedule)
    )


@router.post(
    "/budget-settings/payday-schedules",
    response_model=PaydayScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_payday_schedule(
    payload: PaydayScheduleCreateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> PaydayScheduleResponse:
    if payload.first_day >= payload.second_day:
        raise HTTPException(
            status_code=422, detail="The first cutoff must be before the second cutoff."
        )
    try:
        period = payday_period(payload.effective_from, payload.first_day, payload.second_day)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if period.start != payload.effective_from:
        raise HTTPException(
            status_code=422,
            detail="effective_from must be a payday-period start for the configured cutoffs.",
        )
    latest = db.scalar(
        select(PaydaySchedule)
        .where(PaydaySchedule.user_id == current_user.id)
        .order_by(PaydaySchedule.effective_from.desc())
    )
    if latest is not None and payload.effective_from <= latest.effective_from:
        raise HTTPException(
            status_code=409,
            detail="A payday schedule can only be added after the latest existing schedule.",
        )
    db.query(PaydaySchedule).filter(PaydaySchedule.user_id == current_user.id).update(
        {PaydaySchedule.is_active: False}, synchronize_session=False
    )
    schedule = PaydaySchedule(
        user_id=current_user.id,
        first_day=payload.first_day,
        second_day=payload.second_day,
        effective_from=payload.effective_from,
        is_active=True,
    )
    db.add(schedule)
    db.flush()
    _audit(db, "budget.payday_schedule_created", current_user, request, schedule.id)
    db.commit()
    db.refresh(schedule)
    return _schedule_response(schedule)


@router.get("/budgets/{month_start}", response_model=BudgetCycleResponse)
def get_budget_cycle(
    month_start: date, current_user: ActiveUser, db: DatabaseSession
) -> BudgetCycleResponse:
    month_start = _month_start_or_422(month_start)
    month = calendar_month_period(month_start)
    config = db.scalar(
        select(BudgetConfiguration).where(
            BudgetConfiguration.user_id == current_user.id,
            BudgetConfiguration.month_start == month_start,
        )
    )
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == current_user.id,
                Transaction.transaction_date >= month.start,
                Transaction.transaction_date <= month.end,
            )
        )
    )
    summary = calculate_financial_summary(
        _entries(transactions), config.amount_minor if config else None
    )
    allowances: list[PaydayAllowanceResponse] = []
    allowance_amounts: list[int] = []
    resolved_periods = _payday_periods_for_month(
        db, user_id=current_user.id, month_start=month_start
    )
    if resolved_periods:
        for schedule, period in resolved_periods:
            allowance = db.scalar(
                select(PaydayAllowance).where(
                    PaydayAllowance.user_id == current_user.id,
                    PaydayAllowance.payday_schedule_id == schedule.id,
                    PaydayAllowance.period_start == period.start,
                )
            )
            amount = allowance.amount_minor if allowance else None
            if amount is not None:
                allowance_amounts.append(amount)
            # A payday segment can cross a calendar-month boundary.  Its
            # allowance therefore always includes every transaction in that
            # segment, not only the rows in the requested calendar month.
            period_transactions = list(
                db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == current_user.id,
                        Transaction.transaction_date >= period.start,
                        Transaction.transaction_date <= period.end,
                    )
                )
            )
            allocation = calculate_budget_allocation(_entries(period_transactions), amount)
            allowances.append(
                PaydayAllowanceResponse(
                    period_start=period.start,
                    period_end=period.end,
                    **_allocation_response(allocation).model_dump(),
                )
            )

    category_configs = {
        category_budget.category_id: category_budget.amount_minor
        for category_budget in db.scalars(
            select(CategoryBudget).where(
                CategoryBudget.user_id == current_user.id,
                CategoryBudget.month_start == month_start,
            )
        )
    }
    categories = list(
        db.scalars(
            select(Category).where(
                Category.user_id == current_user.id,
                Category.transaction_type == TransactionType.OUTFLOW,
            )
        )
    )
    category_budgets: list[CategoryBudgetResponse] = []
    for category in categories:
        allocation = calculate_budget_allocation(
            _entries([item for item in transactions if item.category_id == category.id]),
            category_configs.get(category.id),
        )
        category_budgets.append(
            CategoryBudgetResponse(
                category_id=category.id,
                category_name=category.name,
                category_color=category.color,
                **_allocation_response(allocation).model_dump(),
            )
        )
    preferences = db.get(UserPreferences, current_user.id)
    return BudgetCycleResponse(
        month_start=month.start,
        month_end=month.end,
        amount_minor=summary.budget_minor,
        used_minor=summary.budget_used_minor,
        remaining_minor=summary.budget_remaining_minor,
        usage_percent=_decimal_string(summary.budget_usage_percent),
        is_overspent=summary.budget_remaining_minor is not None
        and summary.budget_remaining_minor < 0,
        total_inflow_minor=summary.total_inflow_minor,
        total_outflow_minor=summary.total_outflow_minor,
        net_profit_loss_minor=summary.net_profit_loss_minor,
        reporting_mode=preferences.reporting_mode if preferences else "calendar_month",
        payday_schedule=_schedule_response(
            _schedule_for_date(db, user_id=current_user.id, value=month.end)
        ),
        payday_allowances=allowances,
        allowances_total_minor=sum(allowance_amounts),
        allowances_match_budget=allowance_total_matches_budget(
            allowance_amounts, summary.budget_minor
        ),
        category_budgets=category_budgets,
    )


@router.put("/budgets/{month_start}", response_model=BudgetCycleResponse)
def set_monthly_budget(
    month_start: date,
    payload: BudgetUpdateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> BudgetCycleResponse:
    month_start = _month_start_or_422(month_start)
    config = db.scalar(
        select(BudgetConfiguration).where(
            BudgetConfiguration.user_id == current_user.id,
            BudgetConfiguration.month_start == month_start,
        )
    )
    if config is None:
        config = BudgetConfiguration(
            user_id=current_user.id, month_start=month_start, amount_minor=payload.amount_minor
        )
        db.add(config)
    else:
        config.amount_minor = payload.amount_minor
    db.flush()
    _audit(db, "budget.monthly_amount_set", current_user, request, config.id)
    db.commit()
    return get_budget_cycle(month_start, current_user, db)


@router.put(
    "/budgets/{month_start}/allowances/{period_start}", response_model=PaydayAllowanceResponse
)
def set_payday_allowance(
    month_start: date,
    period_start: date,
    payload: PaydayAllowanceUpdateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> PaydayAllowanceResponse:
    _month_start_or_422(month_start)
    if period_start.year != month_start.year or period_start.month != month_start.month:
        raise HTTPException(
            status_code=422, detail="Allowance period must start in the selected month."
        )
    schedule = _schedule_for_date(db, user_id=current_user.id, value=period_start)
    if schedule is None:
        raise HTTPException(
            status_code=422, detail="Configure payday cutoffs before setting an allowance."
        )
    schedules = list(
        db.scalars(
            select(PaydaySchedule)
            .where(PaydaySchedule.user_id == current_user.id)
            .order_by(PaydaySchedule.effective_from.asc())
        )
    )
    period = versioned_payday_period(period_start, _schedule_versions(schedules))
    if period.start != period_start:
        raise HTTPException(status_code=422, detail="period_start is not a payday-period boundary.")
    allowance = db.scalar(
        select(PaydayAllowance).where(
            PaydayAllowance.user_id == current_user.id,
            PaydayAllowance.payday_schedule_id == schedule.id,
            PaydayAllowance.period_start == period_start,
        )
    )
    if allowance is None:
        allowance = PaydayAllowance(
            user_id=current_user.id,
            payday_schedule_id=schedule.id,
            period_start=period_start,
            amount_minor=payload.amount_minor,
        )
        db.add(allowance)
    else:
        allowance.amount_minor = payload.amount_minor
    db.flush()
    _audit(db, "budget.payday_allowance_set", current_user, request, allowance.id)
    db.commit()
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == current_user.id,
                Transaction.transaction_date >= period.start,
                Transaction.transaction_date <= period.end,
            )
        )
    )
    allocation = calculate_budget_allocation(_entries(transactions), allowance.amount_minor)
    return PaydayAllowanceResponse(
        period_start=period.start,
        period_end=period.end,
        **_allocation_response(allocation).model_dump(),
    )


@router.put(
    "/budgets/{month_start}/categories/{category_id}", response_model=CategoryBudgetResponse
)
def set_category_budget(
    month_start: date,
    category_id: uuid.UUID,
    payload: CategoryBudgetUpdateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> CategoryBudgetResponse:
    month_start = _month_start_or_422(month_start)
    category = _owned_outflow_category_or_422(db, user_id=current_user.id, category_id=category_id)
    category_budget = db.scalar(
        select(CategoryBudget).where(
            CategoryBudget.user_id == current_user.id,
            CategoryBudget.category_id == category_id,
            CategoryBudget.month_start == month_start,
        )
    )
    if category_budget is None:
        category_budget = CategoryBudget(
            user_id=current_user.id,
            category_id=category_id,
            month_start=month_start,
            amount_minor=payload.amount_minor,
        )
        db.add(category_budget)
    else:
        category_budget.amount_minor = payload.amount_minor
    db.flush()
    _audit(db, "budget.category_allocation_set", current_user, request, category_budget.id)
    db.commit()
    month = calendar_month_period(month_start)
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == current_user.id,
                Transaction.category_id == category_id,
                Transaction.transaction_date >= month.start,
                Transaction.transaction_date <= month.end,
            )
        )
    )
    allocation = calculate_budget_allocation(_entries(transactions), category_budget.amount_minor)
    return CategoryBudgetResponse(
        category_id=category.id,
        category_name=category.name,
        category_color=category.color,
        **_allocation_response(allocation).model_dump(),
    )
