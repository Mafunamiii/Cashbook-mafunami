"""Administrator-only account management and self-scoped demo tooling.

User-management endpoints intentionally expose no financial information. The
demo-data endpoint is additionally constrained to the requesting administrator:
it accepts no target account identifier.
"""

from __future__ import annotations

import uuid
from calendar import monthrange
from datetime import date, timedelta

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update

from app.api.dependencies import Administrator, AppSettings, DatabaseSession, require_csrf
from app.api.schemas import (
    AccountStatusUpdateRequest,
    AdminUserResponse,
    DebugClearResponse,
    DebugCycleSeedResponse,
    DebugSeedResponse,
    LegacyCurrencyMigrationRequest,
    LegacyCurrencyMigrationResponse,
    TemporaryPasswordResponse,
)
from app.core.security import generate_secret, hash_password, utc_now
from app.db.models import (
    AuditEvent,
    BudgetConfiguration,
    Category,
    CategoryBudget,
    PaydayAllowance,
    PaydaySchedule,
    Transaction,
    TransactionType,
    User,
    UserPreferences,
)
from app.db.models import Session as AuthSession
from app.domain.currency import IDENTITY_EXCHANGE_RATE, IDENTITY_EXCHANGE_RATE_SOURCE
from app.domain.periods import ReportingPeriod, payday_period
from app.services.exchange_rates import ExchangeRateProviderError, create_exchange_rate_service

router = APIRouter(prefix="/api/v1/admin", tags=["administration"])

_DEMO_TRANSACTIONS = (
    ("Monthly salary (Demo)", "Salary", TransactionType.INFLOW, 8_500_000, 1),
    ("Freelance project (Demo)", "Freelance", TransactionType.INFLOW, 1_850_000, 8),
    ("Weekly groceries (Demo)", "Groceries", TransactionType.OUTFLOW, 485_000, 2),
    ("Electric bill (Demo)", "Bills", TransactionType.OUTFLOW, 312_500, 3),
    ("Internet bill (Demo)", "Bills", TransactionType.OUTFLOW, 169_900, 4),
    ("Lunch with friends (Demo)", "Dining", TransactionType.OUTFLOW, 128_000, 5),
    ("Ride to work (Demo)", "Transport", TransactionType.OUTFLOW, 42_500, 6),
    ("Pharmacy (Demo)", "Health", TransactionType.OUTFLOW, 86_000, 7),
    ("Household supplies (Demo)", "Shopping", TransactionType.OUTFLOW, 214_000, 9),
    ("Movie night (Demo)", "Entertainment", TransactionType.OUTFLOW, 95_000, 10),
    ("Coffee and pastry (Demo)", "Dining", TransactionType.OUTFLOW, 36_500, 12),
    ("Mobile plan (Demo)", "Bills", TransactionType.OUTFLOW, 99_900, 14),
    ("Market groceries (Demo)", "Groceries", TransactionType.OUTFLOW, 376_000, 16),
    ("Fuel top-up (Demo)", "Transport", TransactionType.OUTFLOW, 150_000, 18),
    ("New work shoes (Demo)", "Shopping", TransactionType.OUTFLOW, 275_000, 20),
    ("Weekend dinner (Demo)", "Dining", TransactionType.OUTFLOW, 182_000, 22),
)

_DEMO_CATEGORY_BUDGETS = {
    "Groceries": 1_500_000,
    "Dining": 800_000,
    "Transport": 600_000,
    "Bills": 1_400_000,
    "Health": 500_000,
    "Shopping": 800_000,
    "Entertainment": 400_000,
}


@router.post(
    "/debug/sentry-error",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def send_test_backend_error(
    administrator: Administrator,
    _: None = Depends(require_csrf),
) -> Response:
    """Send an intentional handled exception to the backend Sentry project."""
    _ = administrator
    sentry_sdk.capture_exception(RuntimeError("This is your first backend error!"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _demo_id(user_id: uuid.UUID, month_start: date, resource: str) -> uuid.UUID:
    """Generate stable IDs so retrying the operation never duplicates demo rows."""
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"cashbook:demo:{user_id}:{month_start.isoformat()}:{resource}",
    )


def _completed_demo_periods(today: date) -> list[ReportingPeriod]:
    """Return the four latest fully completed 15th/30th payday periods."""
    periods: list[ReportingPeriod] = []
    cursor = payday_period(today, 15, 30).start - timedelta(days=1)
    while len(periods) < 4:
        period = payday_period(cursor, 15, 30)
        periods.append(period)
        cursor = period.start - timedelta(days=1)
    return list(reversed(periods))


def _audit(
    db: DatabaseSession, event_type: str, actor: User, subject: User, request: Request
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            subject_user_id=subject.id,
            event_type=event_type,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )


def _target(db: DatabaseSession, user_id: uuid.UUID) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return target


def _revoke_sessions(db: DatabaseSession, user_id: uuid.UUID) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(administrator: Administrator, db: DatabaseSession) -> list[AdminUserResponse]:
    # `administrator` is deliberately unused beyond the dependency: it is the
    # authoritative role check and no user-supplied role/owner is trusted.
    _ = administrator
    return [
        AdminUserResponse.model_validate(user)
        for user in db.scalars(select(User).order_by(User.email))
    ]


@router.post(
    "/users/{user_id}/legacy-currency-migration",
    response_model=LegacyCurrencyMigrationResponse,
)
def migrate_legacy_currency(
    user_id: uuid.UUID,
    payload: LegacyCurrencyMigrationRequest,
    request: Request,
    administrator: Administrator,
    db: DatabaseSession,
    settings: AppSettings,
    _: None = Depends(require_csrf),
) -> LegacyCurrencyMigrationResponse:
    """Reassign legacy monetary labels without performing FX conversion."""
    target = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    try:
        supported = create_exchange_rate_service(db, settings).is_available_for_new_selection(
            payload.currency_code
        )
    except ExchangeRateProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Currency choices are temporarily unavailable.",
        ) from exc
    if not supported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Currency is not currently supported by Frankfurter.",
        )
    preferences = db.scalar(
        select(UserPreferences).where(UserPreferences.user_id == user_id).with_for_update()
    )
    if preferences is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account currency settings are unavailable.",
        )
    if payload.currency_code == preferences.currency_code:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Legacy currency migration has already been resolved.",
        )
    legacy_transactions = list(
        db.scalars(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.legacy_currency_record.is_(True),
            )
            .with_for_update()
        )
    )
    if not legacy_transactions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account has no unresolved legacy currency records.",
        )
    if (
        db.scalar(
            select(Transaction.id)
            .where(
                Transaction.user_id == user_id,
                Transaction.legacy_currency_record.is_(False),
            )
            .limit(1)
        )
        is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account contains post-migration transactions and is not eligible for legacy currency migration.",
        )
    previous_currency = preferences.currency_code
    for transaction in legacy_transactions:
        transaction.currency_code = payload.currency_code
        transaction.base_currency_code = payload.currency_code
        transaction.base_amount_minor = transaction.amount_minor
        transaction.exchange_rate = IDENTITY_EXCHANGE_RATE
        transaction.exchange_rate_source = IDENTITY_EXCHANGE_RATE_SOURCE
        transaction.exchange_rate_date = transaction.transaction_date
        transaction.legacy_currency_record = False
    preferences.currency_code = payload.currency_code
    db.add(
        AuditEvent(
            actor_user_id=administrator.id,
            subject_user_id=target.id,
            event_type="admin.legacy_currency_migrated",
            metadata_json={
                "previous_currency_code": previous_currency,
                "new_currency_code": payload.currency_code,
                "legacy_transactions_migrated": len(legacy_transactions),
                "fx_conversion_performed": False,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )
    db.commit()
    return LegacyCurrencyMigrationResponse(
        user_id=target.id,
        previous_currency_code=previous_currency,
        currency_code=preferences.currency_code,
        legacy_transactions_migrated=len(legacy_transactions),
    )


@router.patch("/users/{user_id}/account", response_model=AdminUserResponse)
def set_account_status(
    user_id: uuid.UUID,
    payload: AccountStatusUpdateRequest,
    request: Request,
    administrator: Administrator,
    db: DatabaseSession,
    _: None = Depends(require_csrf),
) -> AdminUserResponse:
    target = _target(db, user_id)
    if target.id == administrator.id and not payload.is_active:
        raise HTTPException(
            status_code=422, detail="Administrators cannot disable their own account."
        )
    target.is_active = payload.is_active
    if not payload.is_active:
        _revoke_sessions(db, target.id)
    _audit(
        db,
        "admin.account_enabled" if payload.is_active else "admin.account_disabled",
        administrator,
        target,
        request,
    )
    db.commit()
    return AdminUserResponse.model_validate(target)


@router.post("/users/{user_id}/temporary-password", response_model=TemporaryPasswordResponse)
def generate_temporary_password(
    user_id: uuid.UUID,
    request: Request,
    administrator: Administrator,
    db: DatabaseSession,
    _: None = Depends(require_csrf),
) -> TemporaryPasswordResponse:
    target = _target(db, user_id)
    temporary_password = generate_secret()
    target.password_hash = hash_password(temporary_password)
    target.password_changed_at = None
    target.must_change_password = True
    _revoke_sessions(db, target.id)
    _audit(db, "admin.temporary_password_generated", administrator, target, request)
    db.commit()
    return TemporaryPasswordResponse(temporary_password=temporary_password)


@router.post(
    "/users/{user_id}/force-password-change",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def force_password_change(
    user_id: uuid.UUID,
    request: Request,
    administrator: Administrator,
    db: DatabaseSession,
    _: None = Depends(require_csrf),
) -> None:
    target = _target(db, user_id)
    target.must_change_password = True
    _revoke_sessions(db, target.id)
    _audit(db, "admin.password_change_forced", administrator, target, request)
    db.commit()


@router.post(
    "/users/{user_id}/sessions/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def revoke_user_sessions(
    user_id: uuid.UUID,
    request: Request,
    administrator: Administrator,
    db: DatabaseSession,
    _: None = Depends(require_csrf),
) -> None:
    target = _target(db, user_id)
    _revoke_sessions(db, target.id)
    _audit(db, "admin.sessions_revoked", administrator, target, request)
    db.commit()


@router.post("/debug/seed-my-account", response_model=DebugSeedResponse)
def seed_requesting_administrator(
    request: Request,
    administrator: Administrator,
    db: DatabaseSession,
    _: None = Depends(require_csrf),
) -> DebugSeedResponse:
    """Add a realistic, retry-safe current-month dataset to the caller only."""
    today = date.today()
    month_start = today.replace(day=1)
    categories = {
        (category.name, category.transaction_type): category
        for category in db.scalars(select(Category).where(Category.user_id == administrator.id))
    }
    required = {(name, transaction_type) for _, name, transaction_type, _, _ in _DEMO_TRANSACTIONS}
    missing = sorted(name for name, kind in required if (name, kind) not in categories)
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"Restore the preset categories before adding demo data: {', '.join(missing)}.",
        )

    budgets_created = 0
    budget_id = _demo_id(administrator.id, month_start, "monthly-budget")
    existing_budget = db.scalar(
        select(BudgetConfiguration.id).where(
            BudgetConfiguration.user_id == administrator.id,
            BudgetConfiguration.month_start == month_start,
        )
    )
    if existing_budget is None:
        db.add(
            BudgetConfiguration(
                id=budget_id,
                user_id=administrator.id,
                month_start=month_start,
                amount_minor=6_500_000,
            )
        )
        budgets_created = 1

    category_budgets_created = 0
    for category_name, amount_minor in _DEMO_CATEGORY_BUDGETS.items():
        category = categories[(category_name, TransactionType.OUTFLOW)]
        existing = db.scalar(
            select(CategoryBudget.id).where(
                CategoryBudget.user_id == administrator.id,
                CategoryBudget.category_id == category.id,
                CategoryBudget.month_start == month_start,
            )
        )
        if existing is None:
            db.add(
                CategoryBudget(
                    id=_demo_id(administrator.id, month_start, f"category-budget:{category_name}"),
                    user_id=administrator.id,
                    category_id=category.id,
                    month_start=month_start,
                    amount_minor=amount_minor,
                )
            )
            category_budgets_created += 1

    transactions_created = 0
    last_day = monthrange(today.year, today.month)[1]
    for index, (name, category_name, transaction_type, amount_minor, preferred_day) in enumerate(
        _DEMO_TRANSACTIONS
    ):
        transaction_id = _demo_id(administrator.id, month_start, f"transaction:{index}")
        if db.get(Transaction, transaction_id) is not None:
            continue
        category = categories[(category_name, transaction_type)]
        db.add(
            Transaction(
                id=transaction_id,
                user_id=administrator.id,
                category_id=category.id,
                name=name,
                transaction_type=transaction_type,
                amount_minor=amount_minor,
                transaction_date=date(
                    today.year,
                    today.month,
                    min(preferred_day, today.day, last_day),
                ),
                notes="Generated by the administrator demo-data tool.",
            )
        )
        transactions_created += 1

    _audit(db, "admin.demo_data_seeded", administrator, administrator, request)
    db.commit()
    return DebugSeedResponse(
        transactions_created=transactions_created,
        budgets_created=budgets_created,
        category_budgets_created=category_budgets_created,
    )


@router.post("/debug/seed-completed-cycles", response_model=DebugCycleSeedResponse)
def seed_completed_cycles(
    request: Request,
    administrator: Administrator,
    db: DatabaseSession,
    _: None = Depends(require_csrf),
) -> DebugCycleSeedResponse:
    """Add about two months of retry-safe, fully completed 15th/30th cycles."""
    periods = _completed_demo_periods(date.today())
    categories = {
        (category.name, category.transaction_type): category
        for category in db.scalars(select(Category).where(Category.user_id == administrator.id))
    }
    required = {(name, kind) for _, name, kind, _, _ in _DEMO_TRANSACTIONS}
    missing = sorted(name for name, kind in required if (name, kind) not in categories)
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                "Restore the preset categories before adding cycle demo data: "
                f"{', '.join(missing)}."
            ),
        )

    schedules = list(
        db.scalars(
            select(PaydaySchedule)
            .where(PaydaySchedule.user_id == administrator.id)
            .order_by(PaydaySchedule.effective_from)
        )
    )
    earliest_start = periods[0].start
    incompatible = [
        schedule
        for schedule in schedules
        if schedule.effective_from <= periods[-1].end
        and (schedule.first_day, schedule.second_day) != (15, 30)
    ]
    if incompatible:
        raise HTTPException(
            status_code=409,
            detail="Existing payday history overlaps these demo periods with different cutoffs.",
        )

    schedule = next(
        (
            item
            for item in reversed(schedules)
            if item.effective_from <= earliest_start
            and (item.first_day, item.second_day) == (15, 30)
        ),
        None,
    )
    schedules_created = 0
    if schedule is None:
        schedule = PaydaySchedule(
            id=_demo_id(administrator.id, earliest_start, "cycle-schedule:15:30"),
            user_id=administrator.id,
            first_day=15,
            second_day=30,
            effective_from=earliest_start,
            is_active=not schedules,
        )
        db.add(schedule)
        schedules_created = 1

    months = sorted(
        {day.replace(day=1) for period in periods for day in (period.start, period.end)}
    )
    budgets_created = 0
    category_budgets_created = 0
    for month_start in months:
        if (
            db.scalar(
                select(BudgetConfiguration.id).where(
                    BudgetConfiguration.user_id == administrator.id,
                    BudgetConfiguration.month_start == month_start,
                )
            )
            is None
        ):
            db.add(
                BudgetConfiguration(
                    id=_demo_id(administrator.id, month_start, "cycle-monthly-budget"),
                    user_id=administrator.id,
                    month_start=month_start,
                    amount_minor=6_500_000,
                )
            )
            budgets_created += 1
        for category_name, amount_minor in _DEMO_CATEGORY_BUDGETS.items():
            category = categories[(category_name, TransactionType.OUTFLOW)]
            if (
                db.scalar(
                    select(CategoryBudget.id).where(
                        CategoryBudget.user_id == administrator.id,
                        CategoryBudget.category_id == category.id,
                        CategoryBudget.month_start == month_start,
                    )
                )
                is None
            ):
                db.add(
                    CategoryBudget(
                        id=_demo_id(
                            administrator.id,
                            month_start,
                            f"cycle-category-budget:{category_name}",
                        ),
                        user_id=administrator.id,
                        category_id=category.id,
                        month_start=month_start,
                        amount_minor=amount_minor,
                    )
                )
                category_budgets_created += 1

    allowances_created = 0
    transactions_created = 0
    transaction_templates = _DEMO_TRANSACTIONS[:8]
    for period_index, period in enumerate(periods):
        period_schedule = max(
            (item for item in (*schedules, schedule) if item.effective_from <= period.start),
            key=lambda item: item.effective_from,
        )
        allowance_id = _demo_id(administrator.id, period.start, "cycle-allowance")
        existing_allowance = db.scalar(
            select(PaydayAllowance.id).where(
                PaydayAllowance.payday_schedule_id == period_schedule.id,
                PaydayAllowance.period_start == period.start,
            )
        )
        if existing_allowance is None:
            db.add(
                PaydayAllowance(
                    id=allowance_id,
                    user_id=administrator.id,
                    payday_schedule_id=period_schedule.id,
                    period_start=period.start,
                    amount_minor=3_250_000,
                )
            )
            allowances_created += 1
        period_days = (period.end - period.start).days + 1
        for item_index, (name, category_name, kind, amount_minor, _) in enumerate(
            transaction_templates
        ):
            transaction_id = _demo_id(
                administrator.id, period.start, f"cycle-transaction:{item_index}"
            )
            if db.get(Transaction, transaction_id) is not None:
                continue
            transaction_day = period.start + timedelta(days=min(item_index * 2, period_days - 1))
            db.add(
                Transaction(
                    id=transaction_id,
                    user_id=administrator.id,
                    category_id=categories[(category_name, kind)].id,
                    name=f"{name} · Cycle {period_index + 1}",
                    transaction_type=kind,
                    amount_minor=amount_minor,
                    transaction_date=transaction_day,
                    notes="Generated by the completed-cycle demo-data tool.",
                )
            )
            transactions_created += 1

    _audit(db, "admin.cycle_demo_data_seeded", administrator, administrator, request)
    db.commit()
    return DebugCycleSeedResponse(
        transactions_created=transactions_created,
        budgets_created=budgets_created,
        category_budgets_created=category_budgets_created,
        schedules_created=schedules_created,
        allowances_created=allowances_created,
    )


@router.delete("/debug/demo-data", response_model=DebugClearResponse)
def clear_requesting_administrator_demo_data(
    request: Request,
    administrator: Administrator,
    db: DatabaseSession,
    _: None = Depends(require_csrf),
) -> DebugClearResponse:
    """Remove only rows whose stable IDs identify them as debugger-created."""
    transactions = list(
        db.scalars(select(Transaction).where(Transaction.user_id == administrator.id))
    )
    demo_transactions = []
    for transaction in transactions:
        month_start = transaction.transaction_date.replace(day=1)
        regular_demo = any(
            transaction.id == _demo_id(administrator.id, month_start, f"transaction:{index}")
            for index in range(len(_DEMO_TRANSACTIONS))
        )
        period_start = payday_period(transaction.transaction_date, 15, 30).start
        cycle_demo = any(
            transaction.id == _demo_id(administrator.id, period_start, f"cycle-transaction:{index}")
            for index in range(8)
        )
        if regular_demo or cycle_demo:
            demo_transactions.append(transaction)

    budgets = list(
        db.scalars(
            select(BudgetConfiguration).where(BudgetConfiguration.user_id == administrator.id)
        )
    )
    demo_budgets = [
        budget
        for budget in budgets
        if budget.id
        in {
            _demo_id(administrator.id, budget.month_start, "monthly-budget"),
            _demo_id(administrator.id, budget.month_start, "cycle-monthly-budget"),
        }
    ]

    category_budgets = list(
        db.scalars(select(CategoryBudget).where(CategoryBudget.user_id == administrator.id))
    )
    demo_category_budgets = [
        budget
        for budget in category_budgets
        if any(
            budget.id
            in {
                _demo_id(
                    administrator.id,
                    budget.month_start,
                    f"category-budget:{category_name}",
                ),
                _demo_id(
                    administrator.id,
                    budget.month_start,
                    f"cycle-category-budget:{category_name}",
                ),
            }
            for category_name in _DEMO_CATEGORY_BUDGETS
        )
    ]

    demo_allowances = [
        allowance
        for allowance in db.scalars(
            select(PaydayAllowance).where(PaydayAllowance.user_id == administrator.id)
        )
        if allowance.id == _demo_id(administrator.id, allowance.period_start, "cycle-allowance")
    ]
    demo_schedules = [
        schedule
        for schedule in db.scalars(
            select(PaydaySchedule).where(PaydaySchedule.user_id == administrator.id)
        )
        if schedule.id
        == _demo_id(administrator.id, schedule.effective_from, "cycle-schedule:15:30")
    ]

    for item in (
        *demo_transactions,
        *demo_allowances,
        *demo_category_budgets,
        *demo_budgets,
        *demo_schedules,
    ):
        db.delete(item)
    _audit(db, "admin.demo_data_cleared", administrator, administrator, request)
    db.commit()
    return DebugClearResponse(
        transactions_deleted=len(demo_transactions),
        budgets_deleted=len(demo_budgets),
        category_budgets_deleted=len(demo_category_budgets),
        allowances_deleted=len(demo_allowances),
        schedules_deleted=len(demo_schedules),
    )
