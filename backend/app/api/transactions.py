"""Owner-scoped transaction entry, history, and search endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from math import ceil
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import Select, case, delete, func, or_, select

from app.api.dependencies import (
    ActiveUser,
    AppSettings,
    CsrfProtectedUser,
    DatabaseSession,
    owned_by_user,
)
from app.api.schemas import (
    StatementTransactionResponse,
    TransactionBulkDeleteRequest,
    TransactionCreateRequest,
    TransactionDeletionResponse,
    TransactionPageResponse,
    TransactionResponse,
    TransactionUpdateRequest,
)
from app.db.models import (
    AuditEvent,
    Category,
    PaydaySchedule,
    Transaction,
    TransactionType,
    UserPreferences,
)
from app.domain.currency import (
    IdentityConversion,
    convert_amount_minor,
    identity_conversion,
    normalize_currency_code,
)
from app.domain.periods import calendar_month_period, versioned_payday_period
from app.services.exchange_rates import (
    ExchangeRateError,
    ExchangeRateProviderError,
    create_exchange_rate_service,
)

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


def _owned_transaction_or_404(
    db: DatabaseSession, transaction_id: uuid.UUID, user_id: uuid.UUID
) -> Transaction:
    transaction = db.scalar(
        owned_by_user(select(Transaction), Transaction, transaction_id, user_id)
    )
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found.")
    return transaction


def _active_owned_category_or_422(
    db: DatabaseSession,
    *,
    category_id: uuid.UUID,
    user_id: uuid.UUID,
    transaction_type: TransactionType,
) -> Category:
    category = db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.user_id == user_id,
            Category.transaction_type == transaction_type,
            Category.archived_at.is_(None),
        )
    )
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose an active category that matches the transaction type.",
        )
    return category


def _clean_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field_name} is required."
        )
    return cleaned


def _require_active_currency_selection(
    currency_code: str, db: DatabaseSession, settings: AppSettings
) -> str:
    currency = normalize_currency_code(currency_code)
    try:
        is_available = create_exchange_rate_service(db, settings).is_available_for_new_selection(
            currency
        )
    except ExchangeRateProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Currency choices are temporarily unavailable.",
        ) from exc
    if not is_available:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Currency is not currently supported by Frankfurter.",
        )
    return currency


def _clean_notes(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _serialize(transaction: Transaction) -> TransactionResponse:
    category = transaction.category
    return TransactionResponse(
        id=transaction.id,
        name=transaction.name,
        transaction_type=transaction.transaction_type,
        category_id=transaction.category_id,
        category_name=category.name,
        category_color=category.color,
        amount_minor=transaction.amount_minor,
        currency_code=transaction.currency_code,
        base_amount_minor=transaction.base_amount_minor,
        base_currency_code=transaction.base_currency_code,
        exchange_rate=transaction.exchange_rate,
        exchange_rate_date=transaction.exchange_rate_date,
        exchange_rate_source=transaction.exchange_rate_source,
        transaction_date=transaction.transaction_date,
        notes=transaction.notes,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
    )


def _base_currency(db: DatabaseSession, user_id: uuid.UUID) -> str:
    preferences = db.get(UserPreferences, user_id)
    if preferences is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account currency settings are unavailable.",
        )
    try:
        return normalize_currency_code(preferences.currency_code)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account currency settings are inconsistent.",
        ) from exc


def _conversion_snapshot(
    db: DatabaseSession,
    settings,
    amount_minor: int,
    currency_code: str,
    base_currency_code: str,
    transaction_date: date,
) -> IdentityConversion:
    if currency_code == base_currency_code:
        return identity_conversion(amount_minor, base_currency_code, transaction_date)
    try:
        rate = create_exchange_rate_service(db, settings).get_exchange_rate(
            currency_code, base_currency_code, transaction_date
        )
        base_amount_minor = convert_amount_minor(
            amount_minor, currency_code, base_currency_code, rate.rate
        )
    except ExchangeRateProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The exchange-rate service is currently unavailable.",
        ) from exc
    except ExchangeRateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No usable exchange rate is available for that date.",
        ) from exc
    except (ArithmeticError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The transaction amount could not be converted.",
        ) from exc
    return IdentityConversion(
        base_amount_minor=base_amount_minor,
        base_currency_code=base_currency_code,
        exchange_rate=rate.rate,
        exchange_rate_date=rate.effective_date,
        exchange_rate_source=rate.source,
    )


def _serialize_statement(
    transaction: Transaction,
    running_balance_minor: int,
    grouping: Literal["calendar_month", "payday"],
    schedules: list[PaydaySchedule],
) -> StatementTransactionResponse:
    """Attach presentation-only grouping data to an owner-scoped row."""
    period = calendar_month_period(transaction.transaction_date)
    if grouping == "payday":
        schedule_versions = [
            (item.effective_from, item.first_day, item.second_day) for item in schedules
        ]
        if schedule_versions:
            period = versioned_payday_period(transaction.transaction_date, schedule_versions)
    return StatementTransactionResponse(
        **_serialize(transaction).model_dump(),
        running_balance_minor=running_balance_minor,
        period_start=period.start,
        period_end=period.end,
    )


def _audit_transaction_event(
    db: DatabaseSession, *, event_type: str, transaction: Transaction, request: Request
) -> None:
    """Audit the action without recording financial content or notes."""
    db.add(
        AuditEvent(
            actor_user_id=transaction.user_id,
            subject_user_id=transaction.user_id,
            event_type=event_type,
            resource_type="transaction",
            resource_id=transaction.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )


def _filtered_transactions(
    *,
    user_id: uuid.UUID,
    date_from: date | None,
    date_to: date | None,
    transaction_type: TransactionType | None,
    category_id: uuid.UUID | None,
    search: str | None,
) -> Select[tuple[Transaction]]:
    statement = select(Transaction).where(Transaction.user_id == user_id)
    if date_from is not None:
        statement = statement.where(Transaction.transaction_date >= date_from)
    if date_to is not None:
        statement = statement.where(Transaction.transaction_date <= date_to)
    if transaction_type is not None:
        statement = statement.where(Transaction.transaction_type == transaction_type)
    if category_id is not None:
        statement = statement.where(Transaction.category_id == category_id)
    if search and (term := search.strip()):
        pattern = f"%{term}%"
        statement = statement.where(
            or_(Transaction.name.ilike(pattern), Transaction.notes.ilike(pattern))
        )
    return statement


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
    settings: AppSettings,
) -> TransactionResponse:
    _active_owned_category_or_422(
        db,
        category_id=payload.category_id,
        user_id=current_user.id,
        transaction_type=payload.transaction_type,
    )
    base_currency = _base_currency(db, current_user.id)
    currency = normalize_currency_code(payload.currency_code or base_currency)
    if currency != base_currency:
        currency = _require_active_currency_selection(currency, db, settings)
    conversion = _conversion_snapshot(
        db, settings, payload.amount_minor, currency, base_currency, payload.transaction_date
    )
    transaction = Transaction(
        user_id=current_user.id,
        category_id=payload.category_id,
        name=_clean_text(payload.name, "Name"),
        transaction_type=payload.transaction_type,
        amount_minor=payload.amount_minor,
        currency_code=currency,
        base_amount_minor=conversion.base_amount_minor,
        base_currency_code=conversion.base_currency_code,
        exchange_rate=conversion.exchange_rate,
        exchange_rate_date=conversion.exchange_rate_date,
        exchange_rate_source=conversion.exchange_rate_source,
        transaction_date=payload.transaction_date,
        notes=_clean_notes(payload.notes),
    )
    db.add(transaction)
    db.flush()
    _audit_transaction_event(
        db, event_type="transaction.created", transaction=transaction, request=request
    )
    db.commit()
    db.refresh(transaction)
    return _serialize(transaction)


@router.get("", response_model=TransactionPageResponse)
def list_transactions(
    current_user: ActiveUser,
    db: DatabaseSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    date_from: date | None = None,
    date_to: date | None = None,
    transaction_type: TransactionType | None = None,
    category_id: uuid.UUID | None = None,
    search: str | None = Query(default=None, max_length=200),
    sort: Literal["newest", "oldest"] = "newest",
    grouping: Literal["calendar_month", "payday"] = "calendar_month",
) -> TransactionPageResponse:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be on or before date_to.",
        )
    # The window is intentionally calculated over every transaction owned by
    # the user first.  Applying statement filters afterwards preserves a
    # consistent cumulative balance even when the visible rows are narrowed.
    running_balance_rows = (
        select(
            Transaction.id.label("transaction_id"),
            func.sum(
                case(
                    (
                        Transaction.transaction_type == TransactionType.INFLOW,
                        Transaction.base_amount_minor,
                    ),
                    else_=-Transaction.base_amount_minor,
                )
            )
            .over(
                order_by=(
                    Transaction.transaction_date.asc(),
                    Transaction.created_at.asc(),
                    Transaction.id.asc(),
                ),
                rows=(None, 0),
            )
            .label("running_balance_minor"),
        )
        .where(Transaction.user_id == current_user.id)
        .subquery()
    )
    statement = _filtered_transactions(
        user_id=current_user.id,
        date_from=date_from,
        date_to=date_to,
        transaction_type=transaction_type,
        category_id=category_id,
        search=search,
    ).join(running_balance_rows, running_balance_rows.c.transaction_id == Transaction.id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    order = (
        (
            Transaction.transaction_date.desc(),
            Transaction.created_at.desc(),
            Transaction.id.desc(),
        )
        if sort == "newest"
        else (
            Transaction.transaction_date.asc(),
            Transaction.created_at.asc(),
            Transaction.id.asc(),
        )
    )
    rows = list(
        db.execute(
            statement.add_columns(running_balance_rows.c.running_balance_minor)
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    schedules = list(
        db.scalars(
            select(PaydaySchedule)
            .where(PaydaySchedule.user_id == current_user.id)
            .order_by(PaydaySchedule.effective_from.desc())
        )
    )
    return TransactionPageResponse(
        items=[
            _serialize_statement(transaction, running_balance, grouping, schedules)
            for transaction, running_balance in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=ceil(total / page_size) if total else 0,
        sort=sort,
    )


@router.delete("", response_model=TransactionDeletionResponse)
def delete_all_transactions(
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> TransactionDeletionResponse:
    """Delete every transaction owned by the caller and no other account."""
    deleted_count = (
        db.scalar(select(func.count(Transaction.id)).where(Transaction.user_id == current_user.id))
        or 0
    )
    db.execute(delete(Transaction).where(Transaction.user_id == current_user.id))
    db.add(
        AuditEvent(
            actor_user_id=current_user.id,
            subject_user_id=current_user.id,
            event_type="transaction.all_deleted",
            resource_type="transaction",
            metadata_json={"deleted_count": deleted_count},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )
    db.commit()
    return TransactionDeletionResponse(transactions_deleted=deleted_count)


@router.delete("/bulk", response_model=TransactionDeletionResponse)
def delete_transactions_bulk(
    payload: TransactionBulkDeleteRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> TransactionDeletionResponse:
    """Atomically delete a bounded set of transactions owned by the caller."""
    transaction_ids = set(payload.transaction_ids)
    owned_ids = set(
        db.scalars(
            select(Transaction.id).where(
                Transaction.user_id == current_user.id,
                Transaction.id.in_(transaction_ids),
            )
        )
    )
    if owned_ids != transaction_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more transactions were not found.",
        )
    db.execute(
        delete(Transaction).where(
            Transaction.user_id == current_user.id,
            Transaction.id.in_(owned_ids),
        )
    )
    db.add(
        AuditEvent(
            actor_user_id=current_user.id,
            subject_user_id=current_user.id,
            event_type="transaction.bulk_deleted",
            resource_type="transaction",
            metadata_json={"deleted_count": len(owned_ids)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )
    db.commit()
    return TransactionDeletionResponse(transactions_deleted=len(owned_ids))


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: uuid.UUID, current_user: ActiveUser, db: DatabaseSession
) -> TransactionResponse:
    return _serialize(_owned_transaction_or_404(db, transaction_id, current_user.id))


@router.patch("/{transaction_id}", response_model=TransactionResponse)
def update_transaction(
    transaction_id: uuid.UUID,
    payload: TransactionUpdateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
    settings: AppSettings,
) -> TransactionResponse:
    transaction = _owned_transaction_or_404(db, transaction_id, current_user.id)
    values = payload.model_dump(exclude_unset=True)
    next_type = values.get("transaction_type", transaction.transaction_type)
    next_category_id = values.get("category_id", transaction.category_id)
    category_changed = (
        next_category_id != transaction.category_id or next_type != transaction.transaction_type
    )
    if category_changed:
        _active_owned_category_or_422(
            db,
            category_id=next_category_id,
            user_id=current_user.id,
            transaction_type=next_type,
        )
    if "name" in values:
        transaction.name = _clean_text(values["name"], "Name")
    financial_fields = {"amount_minor", "currency_code", "transaction_date"}
    if financial_fields.intersection(values):
        base_currency = _base_currency(db, current_user.id)
        if normalize_currency_code(transaction.base_currency_code) != base_currency:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transaction base currency is inconsistent with the account.",
            )
        next_amount = values.get("amount_minor", transaction.amount_minor)
        next_currency = normalize_currency_code(
            values.get("currency_code", transaction.currency_code)
        )
        if next_currency != transaction.currency_code and next_currency != base_currency:
            next_currency = _require_active_currency_selection(next_currency, db, settings)
        next_date = values.get("transaction_date", transaction.transaction_date)
        conversion = _conversion_snapshot(
            db, settings, next_amount, next_currency, base_currency, next_date
        )
        transaction.amount_minor = next_amount
        transaction.currency_code = next_currency
        transaction.transaction_date = next_date
        transaction.base_amount_minor = conversion.base_amount_minor
        transaction.base_currency_code = conversion.base_currency_code
        transaction.exchange_rate = conversion.exchange_rate
        transaction.exchange_rate_date = conversion.exchange_rate_date
        transaction.exchange_rate_source = conversion.exchange_rate_source
    if "notes" in values:
        transaction.notes = _clean_notes(values["notes"])
    transaction.transaction_type = next_type
    transaction.category_id = next_category_id
    _audit_transaction_event(
        db, event_type="transaction.updated", transaction=transaction, request=request
    )
    db.commit()
    db.refresh(transaction)
    return _serialize(transaction)


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: uuid.UUID,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> Response:
    transaction = _owned_transaction_or_404(db, transaction_id, current_user.id)
    _audit_transaction_event(
        db, event_type="transaction.deleted", transaction=transaction, request=request
    )
    db.delete(transaction)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
