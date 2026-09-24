"""Owner-scoped account settings without financial-record access."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.dependencies import ActiveUser, AppSettings, CsrfProtectedUser, DatabaseSession
from app.api.schemas import DashboardSummaryPreferences, SettingsResponse, SettingsUpdateRequest
from app.db.models import (
    AuditEvent,
    BudgetConfiguration,
    CategoryBudget,
    CategoryBudgetResetHistory,
    PaydayAllowance,
    Transaction,
    UserPreferences,
)
from app.domain.currency import normalize_currency_code
from app.services.exchange_rates import ExchangeRateProviderError, create_exchange_rate_service

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _preferences_for_user(db: DatabaseSession, user_id) -> UserPreferences:
    preferences = db.get(UserPreferences, user_id)
    if preferences is None:
        # Registration always provisions preferences. This protects accounts
        # created by an older deployment without allowing a foreign owner ID.
        preferences = UserPreferences(user_id=user_id)
        db.add(preferences)
        db.flush()
    return preferences


def _response(
    user, preferences: UserPreferences, has_financial_data: bool = False
) -> SettingsResponse:
    return SettingsResponse(
        display_name=user.display_name,
        email=user.email,
        currency_code=preferences.currency_code,
        reporting_mode=preferences.reporting_mode,
        appearance_preference=preferences.appearance_preference,
        dashboard_summary=DashboardSummaryPreferences(
            inflow=preferences.dashboard_show_inflow,
            outflow=preferences.dashboard_show_outflow,
            profit_loss=preferences.dashboard_show_profit_loss,
            budget_used=preferences.dashboard_show_budget_used,
        ),
        payday_setup_notice_dismissed=preferences.payday_setup_notice_dismissed,
        has_financial_data=has_financial_data,
    )


def _has_financial_data(db: DatabaseSession, user_id) -> bool:
    financial_models = (
        Transaction,
        BudgetConfiguration,
        CategoryBudget,
        CategoryBudgetResetHistory,
        PaydayAllowance,
    )
    return any(
        db.scalar(select(model.id).where(model.user_id == user_id).limit(1)) is not None
        for model in financial_models
    )


@router.get("", response_model=SettingsResponse)
def get_settings(current_user: ActiveUser, db: DatabaseSession) -> SettingsResponse:
    return _response(
        current_user,
        _preferences_for_user(db, current_user.id),
        _has_financial_data(db, current_user.id),
    )


@router.patch("", response_model=SettingsResponse)
def update_settings(
    payload: SettingsUpdateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
    settings: AppSettings,
) -> SettingsResponse:
    if (
        payload.display_name is None
        and payload.appearance_preference is None
        and payload.dashboard_summary is None
        and payload.payday_setup_notice_dismissed is None
        and payload.currency_code is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No settings supplied."
        )

    preferences = _preferences_for_user(db, current_user.id)
    if (
        payload.currency_code is not None
        and payload.currency_code != preferences.currency_code
        and _has_financial_data(db, current_user.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account currency cannot be changed after financial data exists.",
        )
    if payload.display_name is not None:
        current_user.display_name = payload.display_name.strip()
    if payload.appearance_preference is not None:
        preferences.appearance_preference = payload.appearance_preference
    if payload.dashboard_summary is not None:
        preferences.dashboard_show_inflow = payload.dashboard_summary.inflow
        preferences.dashboard_show_outflow = payload.dashboard_summary.outflow
        preferences.dashboard_show_profit_loss = payload.dashboard_summary.profit_loss
        preferences.dashboard_show_budget_used = payload.dashboard_summary.budget_used
    if payload.payday_setup_notice_dismissed is not None:
        preferences.payday_setup_notice_dismissed = payload.payday_setup_notice_dismissed
    if payload.currency_code is not None:
        currency = normalize_currency_code(payload.currency_code)
        if currency != preferences.currency_code:
            try:
                is_available = create_exchange_rate_service(
                    db, settings
                ).is_available_for_new_selection(currency)
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
        preferences.currency_code = currency
    db.add(
        AuditEvent(
            actor_user_id=current_user.id,
            subject_user_id=current_user.id,
            event_type="user.settings_updated",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )
    db.commit()
    return _response(current_user, preferences, _has_financial_data(db, current_user.id))
