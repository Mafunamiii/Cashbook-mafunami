"""Authentication and authorization dependencies for versioned API routes."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import Settings, get_settings
from app.core.security import hash_secret
from app.db.models import User, UserRole
from app.db.session import get_db_session

DatabaseSession = Annotated[DbSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")


def get_current_user(
    db: DatabaseSession,
    settings: AppSettings,
    request: Request,
) -> User:
    """Resolve an active account from an unrevoked, unexpired server session."""
    session_token = request.cookies.get(settings.session_cookie_name)
    if not session_token:
        raise unauthorized()

    now = datetime.now(UTC)
    # Use explicit columns instead of trusting a client-provided user identity.
    from app.db.models import Session as AuthSession

    user = db.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_hash == hash_secret(session_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_password_change_complete(current_user: CurrentUser) -> User:
    if current_user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change is required before accessing this resource.",
        )
    return current_user


ActiveUser = Annotated[User, Depends(require_password_change_complete)]


def require_admin(current_user: ActiveUser) -> User:
    if current_user.role is not UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required."
        )
    return current_user


Administrator = Annotated[User, Depends(require_admin)]


def require_csrf(
    db: DatabaseSession,
    current_user: CurrentUser,
    settings: AppSettings,
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    """Synchronizer/double-submit CSRF check tied to the authenticated session."""
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    session_token = request.cookies.get(settings.session_cookie_name)
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")

    from app.db.models import Session as AuthSession

    # Resolve the session through the same authenticated user; no client owner
    # identifier is accepted as authority.
    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.user_id == current_user.id,
            AuthSession.token_hash == hash_secret(session_token or ""),
            AuthSession.csrf_secret_hash == hash_secret(csrf_cookie),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")


def get_csrf_protected_user(
    current_user: CurrentUser, _: Annotated[None, Depends(require_csrf)]
) -> User:
    """Require both a valid synchronizer token and a completed password change."""
    return require_password_change_complete(current_user)


CsrfProtectedUser = Annotated[User, Depends(get_csrf_protected_user)]


def owned_by_user(statement, model, resource_id: uuid.UUID, user_id: uuid.UUID):
    """Apply the mandatory owner predicate used for a single resource lookup."""
    return statement.where(model.id == resource_id, model.user_id == user_id)
