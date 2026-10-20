"""Invite-gated registration and server-side session endpoints."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update

from app.api.dependencies import (
    Administrator,
    CsrfProtectedUser,
    CurrentUser,
    DatabaseSession,
    require_csrf,
)
from app.api.schemas import (
    AuthenticatedResponse,
    ChangePasswordRequest,
    LoginRequest,
    RecoveryInfoResponse,
    RegistrationRequest,
    TemporaryPasswordRequest,
    UserResponse,
)
from app.core.config import Settings, get_settings
from app.core.rate_limit import login_rate_limiter
from app.core.security import (
    generate_secret,
    hash_password,
    hash_secret,
    password_needs_rehash,
    session_expiry,
    utc_now,
    verify_password,
)
from app.db.models import (
    AuditEvent,
    Category,
    Session as AuthSession,
    TransactionType,
    User,
    UserPreferences,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

_PRESET_CATEGORIES = (
    ("Salary", "#22c55e", TransactionType.INFLOW),
    ("Freelance", "#14b8a6", TransactionType.INFLOW),
    ("Gifts", "#8b5cf6", TransactionType.INFLOW),
    ("Interest", "#38bdf8", TransactionType.INFLOW),
    ("Groceries", "#f97316", TransactionType.OUTFLOW),
    ("Dining", "#ef4444", TransactionType.OUTFLOW),
    ("Transport", "#eab308", TransactionType.OUTFLOW),
    ("Bills", "#6366f1", TransactionType.OUTFLOW),
    ("Health", "#ec4899", TransactionType.OUTFLOW),
    ("Shopping", "#a855f7", TransactionType.OUTFLOW),
    ("Entertainment", "#06b6d4", TransactionType.OUTFLOW),
    ("Other", "#94a3b8", TransactionType.OUTFLOW),
)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _audit(
    db: DatabaseSession,
    *,
    event_type: str,
    actor: User | None,
    subject: User | None,
    request: Request,
) -> None:
    """Record security events without including credentials, tokens, or data."""
    db.add(
        AuditEvent(
            actor_user_id=actor.id if actor else None,
            subject_user_id=subject.id if subject else None,
            event_type=event_type,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )


def _set_auth_cookies(response: Response, settings: Settings, token: str, csrf_token: str) -> None:
    common = {"secure": settings.cookie_secure, "samesite": settings.cookie_samesite, "path": "/"}
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        max_age=settings.session_ttl_hours * 3600,
        **common,
    )
    # The CSRF value is intentionally readable by the same-origin frontend so
    # it can echo it in X-CSRF-Token. It has no authentication value by itself.
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        max_age=settings.session_ttl_hours * 3600,
        **common,
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def _create_session(
    db: DatabaseSession, user: User, request: Request, settings: Settings
) -> tuple[str, str]:
    token = generate_secret()
    csrf_token = generate_secret()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_secret(token),
            csrf_secret_hash=hash_secret(csrf_token),
            expires_at=session_expiry(settings),
            last_seen_at=utc_now(),
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )
    return token, csrf_token


def _registration_allowed(payload: RegistrationRequest, settings: Settings) -> bool:
    if settings.registration_mode == "open":
        return True
    invite = settings.initial_invite_code
    return bool(
        invite
        and payload.invite_code
        and hmac.compare_digest(invite.get_secret_value(), payload.invite_code)
    )


@router.post("/register", response_model=AuthenticatedResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegistrationRequest,
    response: Response,
    request: Request,
    db: DatabaseSession,
    settings: Settings = Depends(get_settings),
) -> AuthenticatedResponse:
    if not _registration_allowed(payload, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Registration unavailable."
        )
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Registration unavailable."
        )

    user = User(
        email=payload.email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        password_changed_at=utc_now(),
    )
    db.add(user)
    db.flush()
    db.add(UserPreferences(user_id=user.id, currency_code=payload.currency_code))
    db.add_all(
        [
            Category(user_id=user.id, name=name, color=color, transaction_type=transaction_type)
            for name, color, transaction_type in _PRESET_CATEGORIES
        ]
    )
    token, csrf_token = _create_session(db, user, request, settings)
    _audit(db, event_type="user.registered", actor=user, subject=user, request=request)
    db.commit()
    _set_auth_cookies(response, settings, token, csrf_token)
    return AuthenticatedResponse(user=UserResponse.model_validate(user), csrf_token=csrf_token)


@router.post("/login", response_model=AuthenticatedResponse)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: DatabaseSession,
    settings: Settings = Depends(get_settings),
) -> AuthenticatedResponse:
    rate_key = login_rate_limiter.key(payload.email, _client_ip(request))
    if login_rate_limiter.is_limited(
        rate_key, settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many sign-in attempts."
        )

    user = db.scalar(select(User).where(User.email == payload.email))
    if (
        user is None
        or not user.is_active
        or not verify_password(user.password_hash, payload.password)
    ):
        login_rate_limiter.record_failure(rate_key, settings.login_rate_limit_window_seconds)
        _audit(db, event_type="user.login_failed", actor=None, subject=None, request=request)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
        )

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        user.password_changed_at = utc_now()
    login_rate_limiter.clear(rate_key)
    token, csrf_token = _create_session(db, user, request, settings)
    _audit(db, event_type="user.logged_in", actor=user, subject=user, request=request)
    db.commit()
    _set_auth_cookies(response, settings, token, csrf_token)
    return AuthenticatedResponse(user=UserResponse.model_validate(user), csrf_token=csrf_token)


@router.get("/session", response_model=UserResponse)
def session_details(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
    settings: Settings = Depends(get_settings),
) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        auth_session = db.scalar(
            select(AuthSession).where(
                AuthSession.user_id == current_user.id,
                AuthSession.token_hash == hash_secret(token),
                AuthSession.revoked_at.is_(None),
            )
        )
        if auth_session:
            auth_session.revoked_at = utc_now()
            _audit(
                db,
                event_type="user.logged_out",
                actor=current_user,
                subject=current_user,
                request=request,
            )
            db.commit()
    _clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    response: Response,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
    settings: Settings = Depends(get_settings),
) -> Response:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == current_user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )
    _audit(
        db,
        event_type="user.logged_out_all",
        actor=current_user,
        subject=current_user,
        request=request,
    )
    db.commit()
    _clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/change-password", response_model=AuthenticatedResponse)
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> AuthenticatedResponse:
    if not verify_password(current_user.password_hash, payload.current_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect."
        )

    current_user.password_hash = hash_password(payload.new_password)
    current_user.password_changed_at = utc_now()
    current_user.must_change_password = False
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == current_user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )
    token, csrf_token = _create_session(db, current_user, request, settings)
    _audit(
        db,
        event_type="user.password_changed",
        actor=current_user,
        subject=current_user,
        request=request,
    )
    db.commit()
    _set_auth_cookies(response, settings, token, csrf_token)
    return AuthenticatedResponse(
        user=UserResponse.model_validate(current_user), csrf_token=csrf_token
    )


@router.get("/recovery-info", response_model=RecoveryInfoResponse)
def recovery_info(settings: Settings = Depends(get_settings)) -> RecoveryInfoResponse:
    return RecoveryInfoResponse(message=settings.manual_recovery_message)


@router.post("/admin/users/{user_id}/temporary-password", status_code=status.HTTP_204_NO_CONTENT)
def issue_temporary_password(
    user_id: str,
    payload: TemporaryPasswordRequest,
    request: Request,
    administrator: Administrator,
    db: DatabaseSession,
    _: None = Depends(require_csrf),
) -> Response:
    target = db.scalar(select(User).where(User.id == user_id))
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    target.password_hash = hash_password(payload.temporary_password)
    target.password_changed_at = None
    target.must_change_password = True
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )
    _audit(
        db,
        event_type="admin.temporary_password_issued",
        actor=administrator,
        subject=target,
        request=request,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
