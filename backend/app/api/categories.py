"""Owner-scoped category management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select

from app.api.dependencies import ActiveUser, CsrfProtectedUser, DatabaseSession, owned_by_user
from app.api.schemas import CategoryCreateRequest, CategoryResponse, CategoryUpdateRequest
from app.core.security import utc_now
from app.db.models import AuditEvent, Category, CategoryBudget, Transaction

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])

# These restrained, accessible swatches are the only colors accepted for a
# category. Keeping this server-side prevents arbitrary CSS values from being
# stored or rendered later in reports.
CURATED_CATEGORY_COLORS = frozenset(
    {
        "#22c55e",
        "#14b8a6",
        "#8b5cf6",
        "#38bdf8",
        "#f97316",
        "#ef4444",
        "#eab308",
        "#6366f1",
        "#ec4899",
        "#a855f7",
        "#06b6d4",
        "#94a3b8",
    }
)


def _owned_category_or_404(
    db: DatabaseSession, category_id: uuid.UUID, user_id: uuid.UUID
) -> Category:
    category = db.scalar(owned_by_user(select(Category), Category, category_id, user_id))
    if category is None:
        # Deliberately indistinguishable from a missing resource.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return category


def _normalized_category_fields(
    name: str, color: str, icon: str | None
) -> tuple[str, str, str | None]:
    normalized_name = name.strip()
    normalized_color = color.strip().lower()
    normalized_icon = icon.strip() if icon else None
    if not normalized_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name is required."
        )
    if normalized_color not in CURATED_CATEGORY_COLORS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose a curated category color.",
        )
    return normalized_name, normalized_color, normalized_icon or None


def _ensure_unique_name(
    db: DatabaseSession,
    *,
    user_id: uuid.UUID,
    name: str,
    transaction_type,
    excluding_id: uuid.UUID | None = None,
) -> None:
    statement = select(Category.id).where(
        Category.user_id == user_id,
        Category.transaction_type == transaction_type,
        func.lower(Category.name) == name.casefold(),
    )
    if excluding_id is not None:
        statement = statement.where(Category.id != excluding_id)
    if db.scalar(statement) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A category with this name and type already exists.",
        )


def _audit_category_event(
    db: DatabaseSession, *, event_type: str, category: Category, request: Request
) -> None:
    """Keep an ownership audit trail without storing category content or money."""
    db.add(
        AuditEvent(
            actor_user_id=category.user_id,
            subject_user_id=category.user_id,
            event_type=event_type,
            resource_type="category",
            resource_id=category.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:512] or None,
        )
    )


@router.get("", response_model=list[CategoryResponse])
def list_categories(
    current_user: ActiveUser,
    db: DatabaseSession,
    include_archived: bool = Query(default=False),
) -> list[Category]:
    statement = select(Category).where(Category.user_id == current_user.id)
    if not include_archived:
        statement = statement.where(Category.archived_at.is_(None))
    return list(
        db.scalars(statement.order_by(Category.transaction_type, func.lower(Category.name)))
    )


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> Category:
    name, color, icon = _normalized_category_fields(payload.name, payload.color, payload.icon)
    _ensure_unique_name(
        db, user_id=current_user.id, name=name, transaction_type=payload.transaction_type
    )
    category = Category(
        user_id=current_user.id,
        name=name,
        color=color,
        icon=icon,
        transaction_type=payload.transaction_type,
    )
    db.add(category)
    db.flush()
    _audit_category_event(db, event_type="category.created", category=category, request=request)
    db.commit()
    db.refresh(category)
    return category


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category(category_id: uuid.UUID, current_user: ActiveUser, db: DatabaseSession) -> Category:
    return _owned_category_or_404(db, category_id, current_user.id)


@router.patch("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdateRequest,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> Category:
    category = _owned_category_or_404(db, category_id, current_user.id)
    values = payload.model_dump(exclude_unset=True)
    name, color, icon = _normalized_category_fields(
        values.get("name", category.name),
        values.get("color", category.color),
        values.get("icon", category.icon),
    )
    _ensure_unique_name(
        db,
        user_id=current_user.id,
        name=name,
        transaction_type=category.transaction_type,
        excluding_id=category.id,
    )
    category.name = name
    category.color = color
    category.icon = icon
    _audit_category_event(db, event_type="category.updated", category=category, request=request)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: uuid.UUID,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> Response:
    category = _owned_category_or_404(db, category_id, current_user.id)
    has_transactions = db.scalar(
        select(Transaction.id).where(
            Transaction.user_id == current_user.id,
            Transaction.category_id == category.id,
        )
    )
    has_budgets = db.scalar(
        select(CategoryBudget.id).where(
            CategoryBudget.user_id == current_user.id,
            CategoryBudget.category_id == category.id,
        )
    )
    if has_transactions is not None or has_budgets is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This category is used by transactions or budgets. "
                "Archive it to preserve those records."
            ),
        )
    _audit_category_event(db, event_type="category.deleted", category=category, request=request)
    db.delete(category)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{category_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_category_explicit(
    category_id: uuid.UUID,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> Response:
    category = _owned_category_or_404(db, category_id, current_user.id)
    if category.archived_at is None:
        category.archived_at = utc_now()
        _audit_category_event(
            db, event_type="category.archived", category=category, request=request
        )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{category_id}/restore", response_model=CategoryResponse)
def restore_category(
    category_id: uuid.UUID,
    request: Request,
    current_user: CsrfProtectedUser,
    db: DatabaseSession,
) -> Category:
    category = _owned_category_or_404(db, category_id, current_user.id)
    if category.archived_at is not None:
        category.archived_at = None
        _audit_category_event(
            db, event_type="category.restored", category=category, request=request
        )
        db.commit()
        db.refresh(category)
    return category
