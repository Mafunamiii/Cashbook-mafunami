"""Owner-scoped account settings without financial-record access."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.dependencies import ActiveUser, CsrfProtectedUser, DatabaseSession
from app.api.schemas import SettingsResponse, SettingsUpdateRequest
from app.db.models import AuditEvent, UserPreferences

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


def _response(user, preferences: UserPreferences) -> SettingsResponse:
    return SettingsResponse(
        display_name=user.display_name,
        email=user.email,
        reporting_mode=preferences.reporting_mode,
        appearance_preference=preferences.appearance_preference,
    )


@router.get("", response_model=SettingsResponse)
def get_settings(current_user: ActiveUser, db: DatabaseSession) -> SettingsResponse:
    return _response(current_user, _preferences_for_user(db, current_user.id))


@router.patch("", response_model=SettingsResponse)
def update_settings(
    payload: SettingsUpdateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> SettingsResponse:
    if payload.display_name is None and payload.appearance_preference is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No settings supplied."
        )

    preferences = _preferences_for_user(db, current_user.id)
    if payload.display_name is not None:
        current_user.display_name = payload.display_name.strip()
    if payload.appearance_preference is not None:
        preferences.appearance_preference = payload.appearance_preference
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
    return _response(current_user, preferences)
