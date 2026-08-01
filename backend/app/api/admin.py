"""Minimal administrator-only account management.

These endpoints intentionally expose no categories, budgets, transactions, or
reports.  They operate solely on account and session state.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update

from app.api.dependencies import Administrator, DatabaseSession, require_csrf
from app.api.schemas import (
    AccountStatusUpdateRequest,
    AdminUserResponse,
    TemporaryPasswordResponse,
)
from app.core.security import generate_secret, hash_password, utc_now
from app.db.models import AuditEvent, User
from app.db.models import Session as AuthSession

router = APIRouter(prefix="/api/v1/admin", tags=["administration"])


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
