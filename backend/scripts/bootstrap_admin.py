"""Create or promote the application's main administrator account."""

from __future__ import annotations

import argparse
import secrets

from sqlalchemy import select

from app.core.security import hash_password, utc_now
from app.db.models import Category, TransactionType, User, UserPreferences, UserRole
from app.db.session import create_session_factory

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", default="Main Administrator")
    parser.add_argument(
        "--temporary-password",
        help="At least 12 characters. If omitted, a secure value is generated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    email = args.email.strip().casefold()
    if email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
        raise SystemExit("Enter a valid administrator email address.")

    password = args.temporary_password or secrets.token_urlsafe(18)
    if len(password) < 12:
        raise SystemExit("The temporary password must be at least 12 characters.")

    with create_session_factory()() as db:
        user = db.scalar(select(User).where(User.email == email))
        action = "updated"
        if user is None:
            action = "created"
            user = User(
                email=email,
                display_name=args.display_name.strip(),
                password_hash=hash_password(password),
                password_changed_at=utc_now(),
            )
            db.add(user)
            db.flush()
            db.add(UserPreferences(user_id=user.id))
            db.add_all(
                Category(
                    user_id=user.id,
                    name=name,
                    color=color,
                    transaction_type=transaction_type,
                )
                for name, color, transaction_type in _PRESET_CATEGORIES
            )
        else:
            user.password_hash = hash_password(password)
            user.display_name = args.display_name.strip()
            user.password_changed_at = utc_now()

        user.role = UserRole.ADMIN
        user.is_active = True
        user.must_change_password = True
        db.commit()

    print(f"Administrator {action}: {email}")
    print(f"Temporary password: {password}")
    print("The administrator must change this password after signing in.")


if __name__ == "__main__":
    main()
