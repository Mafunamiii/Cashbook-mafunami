from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditEvent,
    BudgetConfiguration,
    Category,
    CategoryBudget,
    CategoryBudgetResetHistory,
    PaydayAllowance,
    PaydaySchedule,
    Session as AuthSession,
    Transaction,
    TransactionType,
    User,
    UserPreferences,
    UserRole,
)

pytestmark = pytest.mark.integration


def register(
    client: TestClient, email: str, display_name: str, currency_code: str = "PHP"
) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": display_name,
            "password": "a-long-integration-password",
            "currency_code": currency_code,
            "invite_code": "integration-invite-code",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, email: str, password: str = "a-long-integration-password") -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def category_for(db_session: Session, user_id: str) -> Category:
    category = db_session.scalar(
        select(Category).where(Category.user_id == uuid.UUID(user_id)).order_by(Category.name)
    )
    assert category is not None
    return category


def csrf_headers(client: TestClient, csrf_token: str) -> dict[str, str]:
    assert client.cookies.get("cashbook_csrf") == csrf_token
    return {"X-CSRF-Token": csrf_token}


def create_transaction(
    client: TestClient,
    *,
    csrf_token: str,
    category: Category,
    name: str = "A transaction",
    amount_minor: int = 1_250,
    transaction_date: str = "2026-08-01",
    notes: str | None = None,
    currency_code: str | None = None,
) -> dict:
    payload = {
        "name": name,
        "transaction_type": category.transaction_type.value,
        "category_id": str(category.id),
        "amount_minor": amount_minor,
        "transaction_date": transaction_date,
        "notes": notes,
    }
    if currency_code is not None:
        payload["currency_code"] = currency_code
    response = client.post(
        "/api/v1/transactions",
        json=payload,
        headers=csrf_headers(client, csrf_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


class StubExchangeRateService:
    def __init__(self, rates: dict[tuple[str, str, date], Decimal]) -> None:
        self.rates = rates
        self.calls: list[tuple[str, str, date]] = []

    def get_exchange_rate(self, source: str, target: str, requested_date: date):
        from app.services.exchange_rates import ExchangeRateResult

        self.calls.append((source, target, requested_date))
        rate = self.rates[(source, target, requested_date)]
        return ExchangeRateResult(rate, requested_date, requested_date, "test-provider")

    def is_available_for_new_selection(self, currency_code: str) -> bool:
        return True


class ActiveCurrencyService:
    def is_available_for_new_selection(self, currency_code: str) -> bool:
        return True


def category_of_type(
    db_session: Session, user_id: str, transaction_type: TransactionType
) -> Category:
    category = db_session.scalar(
        select(Category).where(
            Category.user_id == uuid.UUID(user_id), Category.transaction_type == transaction_type
        )
    )
    assert category is not None
    return category


def test_dashboard_is_owner_scoped_and_uses_only_outflows_for_its_chart(
    client: TestClient, db_session: Session
) -> None:
    user_a = register(client, "dashboard-a@example.test", "Dashboard A")
    outflow = category_of_type(db_session, user_a["user"]["id"], TransactionType.OUTFLOW)
    inflow = category_of_type(db_session, user_a["user"]["id"], TransactionType.INFLOW)
    headers = csrf_headers(client, user_a["csrf_token"])
    assert (
        client.put(
            "/api/v1/budgets/2026-08-01", json={"amount_minor": 10_000}, headers=headers
        ).status_code
        == 200
    )
    create_transaction(
        client,
        csrf_token=user_a["csrf_token"],
        category=outflow,
        name="Outflow for chart",
        amount_minor=3_000,
        transaction_date="2026-08-04",
    )
    create_transaction(
        client,
        csrf_token=user_a["csrf_token"],
        category=inflow,
        name="Income excluded from chart",
        amount_minor=9_000,
        transaction_date="2026-08-05",
    )

    dashboard = client.get("/api/v1/dashboard?anchor_date=2026-08-10&period_mode=calendar_month")
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["total_inflow_minor"] == 9_000
    assert payload["total_outflow_minor"] == 3_000
    assert payload["remaining_minor"] == 7_000
    assert [
        (item["category_name"], item["used_minor"]) for item in payload["category_spending"]
    ] == [(outflow.name, 3_000)]
    assert {item["name"] for item in payload["recent_transactions"]} == {
        "Outflow for chart",
        "Income excluded from chart",
    }

    user_b = register(client, "dashboard-b@example.test", "Dashboard B")
    assert client.get("/api/v1/dashboard?anchor_date=2026-08-10").json()["total_outflow_minor"] == 0
    assert not client.get("/api/v1/dashboard?anchor_date=2026-08-10").json()["recent_transactions"]
    assert user_b["user"]["id"] != user_a["user"]["id"]


def test_dashboard_includes_zero_spend_and_overspent_category_budgets(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "dashboard-budgets@example.test", "Dashboard Budgets")
    user_id = uuid.UUID(registered["user"]["id"])
    outflows = list(
        db_session.scalars(
            select(Category)
            .where(
                Category.user_id == user_id,
                Category.transaction_type == TransactionType.OUTFLOW,
            )
            .order_by(Category.name)
            .limit(2)
        )
    )
    assert len(outflows) == 2
    headers = csrf_headers(client, registered["csrf_token"])
    for category, amount in zip(outflows, (5_000, 1_000), strict=True):
        response = client.put(
            f"/api/v1/budgets/2026-08-01/categories/{category.id}",
            json={"amount_minor": amount},
            headers=headers,
        )
        assert response.status_code == 200, response.text
    create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=outflows[1],
        amount_minor=1_500,
        transaction_date="2026-08-08",
    )

    response = client.get("/api/v1/dashboard?anchor_date=2026-08-10")
    assert response.status_code == 200, response.text
    budgets = {item["category_id"]: item for item in response.json()["category_budgets"]}
    assert budgets[str(outflows[0].id)]["used_minor"] == 0
    assert budgets[str(outflows[0].id)]["remaining_minor"] == 5_000
    assert budgets[str(outflows[1].id)]["remaining_minor"] == -500
    assert budgets[str(outflows[1].id)]["is_overspent"] is True


def test_category_budget_clear_unsets_without_collapsing_explicit_zero(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "category-bulk@example.test", "Category Bulk")
    user_id = registered["user"]["id"]
    categories = list(
        db_session.scalars(
            select(Category)
            .where(
                Category.user_id == uuid.UUID(user_id),
                Category.transaction_type == TransactionType.OUTFLOW,
            )
            .order_by(Category.name)
            .limit(3)
        )
    )
    headers = csrf_headers(client, registered["csrf_token"])
    for category, amount in zip(categories[:2], (12_500, 0), strict=True):
        assert client.put(
            f"/api/v1/budgets/2026-08-01/categories/{category.id}",
            json={"amount_minor": amount},
            headers=headers,
        ).status_code == 200

    cleared = client.put(
        f"/api/v1/budgets/2026-08-01/categories/{categories[0].id}",
        json={"amount_minor": None},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["amount_minor"] is None
    assert cleared.json()["remaining_minor"] is None

    cycle = client.get("/api/v1/budgets/2026-08-01")
    by_category = {item["category_id"]: item for item in cycle.json()["category_budgets"]}
    assert by_category[str(categories[0].id)]["amount_minor"] is None
    assert by_category[str(categories[1].id)]["amount_minor"] == 0
    assert by_category[str(categories[2].id)]["amount_minor"] is None
    assert db_session.scalar(
        select(CategoryBudget).where(
            CategoryBudget.user_id == uuid.UUID(user_id),
            CategoryBudget.category_id == categories[0].id,
            CategoryBudget.month_start == date(2026, 8, 1),
        )
    ) is None

    omitted = client.put(
        f"/api/v1/budgets/2026-08-01/categories/{categories[1].id}",
        json={"reset_each_payday": False},
        headers=headers,
    )
    assert omitted.status_code == 422
    still_zero = db_session.scalar(
        select(CategoryBudget).where(
            CategoryBudget.user_id == uuid.UUID(user_id),
            CategoryBudget.category_id == categories[1].id,
            CategoryBudget.month_start == date(2026, 8, 1),
        )
    )
    assert still_zero is not None and still_zero.amount_minor == 0


def test_category_budget_payday_reset_preserves_cycle_history(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "category-reset@example.test", "Category Reset")
    user_id = registered["user"]["id"]
    category = category_of_type(db_session, user_id, TransactionType.OUTFLOW)
    headers = csrf_headers(client, registered["csrf_token"])
    schedule = client.post(
        "/api/v1/budget-settings/payday-schedules",
        json={"first_day": 1, "second_day": 2, "effective_from": "2026-07-01"},
        headers=headers,
    )
    assert schedule.status_code == 201, schedule.text
    saved = client.put(
        f"/api/v1/budgets/2026-07-01/categories/{category.id}",
        json={"amount_minor": 12_500, "reset_each_payday": True},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["reset_each_payday"] is True

    db_session.refresh(category)
    category.budget_reset_anchor = date(2026, 7, 2)
    db_session.commit()

    cycle = client.get("/api/v1/budgets/2026-08-01")
    assert cycle.status_code == 200, cycle.text
    allocation = next(
        item for item in cycle.json()["category_budgets"] if item["category_id"] == str(category.id)
    )
    assert allocation["amount_minor"] == 0
    assert allocation["reset_each_payday"] is True
    history = db_session.scalar(
        select(CategoryBudgetResetHistory).where(
            CategoryBudgetResetHistory.user_id == uuid.UUID(user_id),
            CategoryBudgetResetHistory.category_id == category.id,
            CategoryBudgetResetHistory.period_start == date(2026, 7, 2),
        )
    )
    assert history is not None
    assert history.amount_minor == 12_500
    july_budget = db_session.scalar(
        select(CategoryBudget).where(
            CategoryBudget.user_id == uuid.UUID(user_id),
            CategoryBudget.category_id == category.id,
            CategoryBudget.month_start == date(2026, 7, 1),
        )
    )
    assert july_budget is not None
    assert july_budget.amount_minor == 12_500


def test_invite_only_registration_rejects_missing_or_wrong_code(client: TestClient) -> None:
    payload = {
        "email": "first@example.test",
        "display_name": "First User",
        "password": "a-long-integration-password",
        "currency_code": "PHP",
    }
    assert client.post("/api/v1/auth/register", json=payload).status_code == 403
    assert (
        client.post("/api/v1/auth/register", json={**payload, "invite_code": "wrong"}).status_code
        == 403
    )


def test_registration_requires_explicit_supported_currency(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "explicit-currency@example.test",
            "display_name": "Explicit Currency",
            "password": "a-long-integration-password",
            "invite_code": "integration-invite-code",
        },
    )
    assert response.status_code == 422

    selected = register(
        client, "selected-currency@example.test", "Selected Currency", currency_code="AED"
    )
    preferences = db_session.get(UserPreferences, uuid.UUID(selected["user"]["id"]))
    assert preferences is not None and preferences.currency_code == "AED"


def test_registration_creates_the_curated_preset_categories(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "presets@example.test", "Preset User")
    categories = list(
        db_session.scalars(
            select(Category).where(Category.user_id == uuid.UUID(registered["user"]["id"]))
        )
    )

    assert len(categories) == 12
    assert {category.name for category in categories} >= {"Salary", "Groceries", "Other"}
    assert sum(category.transaction_type is TransactionType.INFLOW for category in categories) == 4
    assert sum(category.transaction_type is TransactionType.OUTFLOW for category in categories) == 8
    assert all(category.color.startswith("#") for category in categories)


def test_category_lifecycle_supports_custom_types_archive_and_restore(
    client: TestClient,
) -> None:
    registered = register(client, "categories@example.test", "Category User")
    headers = csrf_headers(client, registered["csrf_token"])

    created = client.post(
        "/api/v1/categories",
        json={
            "name": "Side project",
            "color": "#06B6D4",
            "icon": "briefcase",
            "transaction_type": "inflow",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    category = created.json()
    assert category["color"] == "#06b6d4"
    assert category["icon"] == "briefcase"

    renamed = client.patch(
        f"/api/v1/categories/{category['id']}",
        json={"name": "Consulting", "color": "#22c55e", "icon": None},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Consulting"
    assert renamed.json()["icon"] is None

    assert (
        client.post(f"/api/v1/categories/{category['id']}/archive", headers=headers).status_code
        == 204
    )
    active = client.get("/api/v1/categories")
    assert active.status_code == 200
    assert category["id"] not in {item["id"] for item in active.json()}
    archived = client.get("/api/v1/categories?include_archived=true")
    assert next(item for item in archived.json() if item["id"] == category["id"])["archived_at"]

    restored = client.post(f"/api/v1/categories/{category['id']}/restore", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None

    deleted = client.delete(f"/api/v1/categories/{category['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/categories/{category['id']}").status_code == 404


def test_category_color_accepts_arbitrary_hex_and_rejects_invalid_values(
    client: TestClient,
) -> None:
    registered = register(client, "category-colors@example.test", "Category Colors")
    headers = csrf_headers(client, registered["csrf_token"])

    created = client.post(
        "/api/v1/categories",
        json={"name": "Custom color", "color": "#Ab12Ef", "transaction_type": "outflow"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["color"] == "#ab12ef"

    invalid = client.post(
        "/api/v1/categories",
        json={"name": "Invalid color", "color": "#12gg34", "transaction_type": "outflow"},
        headers=headers,
    )
    assert invalid.status_code == 422


def test_preset_category_can_be_permanently_deleted(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "delete-preset@example.test", "Delete Preset")
    category = category_for(db_session, registered["user"]["id"])
    category_id = category.id

    response = client.delete(
        f"/api/v1/categories/{category_id}",
        headers=csrf_headers(client, registered["csrf_token"]),
    )

    assert response.status_code == 204
    db_session.expire_all()
    assert db_session.get(Category, category_id) is None


def test_category_delete_is_blocked_when_transactions_reference_it(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "referenced@example.test", "Referenced User")
    category = category_for(db_session, registered["user"]["id"])
    db_session.add(
        Transaction(
            user_id=category.user_id,
            category_id=category.id,
            transaction_type=category.transaction_type,
            name="Historical expense",
            amount_minor=100,
            transaction_date=date(2026, 8, 1),
        )
    )
    db_session.commit()

    response = client.delete(
        f"/api/v1/categories/{category.id}", headers=csrf_headers(client, registered["csrf_token"])
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This category cannot be permanently deleted because it is used by "
        "transactions or budgets. Archive it instead to preserve those records."
    )
    db_session.expire_all()
    stored_category = db_session.get(Category, category.id)
    assert stored_category is not None
    assert stored_category.archived_at is None
    assert db_session.scalar(select(Transaction.id).where(Transaction.category_id == category.id))


def test_category_delete_is_blocked_when_budgets_reference_it(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "budget-referenced@example.test", "Budget Referenced")
    category = category_for(db_session, registered["user"]["id"])
    db_session.add(
        CategoryBudget(
            user_id=category.user_id,
            category_id=category.id,
            month_start=date(2026, 8, 1),
            amount_minor=100,
        )
    )
    db_session.commit()

    response = client.delete(
        f"/api/v1/categories/{category.id}", headers=csrf_headers(client, registered["csrf_token"])
    )
    assert response.status_code == 409
    assert "Archive it instead" in response.json()["detail"]
    db_session.expire_all()
    assert db_session.get(Category, category.id) is not None


def test_user_cannot_read_modify_or_archive_another_users_category(
    client: TestClient, db_session: Session
) -> None:
    user_a = register(client, "a@example.test", "User A")
    csrf_a = user_a["csrf_token"]
    user_b = register(client, "b@example.test", "User B")
    category_b = category_for(db_session, user_b["user"]["id"])

    login(client, "a@example.test")
    assert client.get(f"/api/v1/categories/{category_b.id}").status_code == 404
    assert (
        client.patch(
            f"/api/v1/categories/{category_b.id}",
            json={"name": "Taken over"},
            headers=csrf_headers(client, client.cookies.get("cashbook_csrf") or csrf_a),
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/categories/{category_b.id}",
            headers=csrf_headers(client, client.cookies.get("cashbook_csrf") or csrf_a),
        ).status_code
        == 404
    )

    user_b_session = login(client, "b@example.test")
    unchanged = client.get(f"/api/v1/categories/{category_b.id}")
    assert unchanged.status_code == 200
    assert unchanged.json()["name"] == category_b.name
    assert unchanged.json()["archived_at"] is None
    assert (
        client.delete(
            f"/api/v1/categories/{category_b.id}",
            headers=csrf_headers(client, user_b_session["csrf_token"]),
        ).status_code
        == 204
    )


def test_csrf_revocation_and_disabled_account_are_enforced(
    client: TestClient, db_session: Session
) -> None:
    session_data = register(client, "user@example.test", "User")
    user_id = session_data["user"]["id"]
    category = category_for(db_session, user_id)

    assert (
        client.patch(f"/api/v1/categories/{category.id}", json={"name": "Blocked"}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/auth/logout", headers=csrf_headers(client, session_data["csrf_token"])
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/session").status_code == 401

    login(client, "user@example.test")
    user = db_session.scalar(select(User).where(User.id == uuid.UUID(user_id)))
    assert user is not None
    user.is_active = False
    db_session.commit()
    assert client.get("/api/v1/auth/session").status_code == 401


def test_temporary_password_requires_change_before_data_access(
    client: TestClient, db_session: Session
) -> None:
    admin_data = register(client, "admin@example.test", "Administrator")
    target_data = register(client, "target@example.test", "Target")
    admin = db_session.scalar(select(User).where(User.id == uuid.UUID(admin_data["user"]["id"])))
    assert admin is not None
    admin.role = UserRole.ADMIN
    db_session.commit()

    admin_session = login(client, "admin@example.test")
    response = client.post(
        f"/api/v1/auth/admin/users/{target_data['user']['id']}/temporary-password",
        json={"temporary_password": "temporary-password-value"},
        headers=csrf_headers(client, admin_session["csrf_token"]),
    )
    assert response.status_code == 204, response.text

    target_session = login(client, "target@example.test", "temporary-password-value")
    target_category = category_for(db_session, target_data["user"]["id"])
    assert client.get(f"/api/v1/categories/{target_category.id}").status_code == 403
    changed = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "temporary-password-value",
            "new_password": "a-new-long-integration-password",
        },
        headers=csrf_headers(client, target_session["csrf_token"]),
    )
    assert changed.status_code == 200, changed.text
    assert client.get(f"/api/v1/categories/{target_category.id}").status_code == 200


def test_settings_are_owner_scoped_and_update_profile_and_appearance(client: TestClient) -> None:
    registered = register(client, "settings@example.test", "Before")
    initial = client.get("/api/v1/settings")
    assert initial.status_code == 200
    assert initial.json() == {
        "display_name": "Before",
        "email": "settings@example.test",
        "currency_code": "PHP",
        "reporting_mode": "calendar_month",
        "appearance_preference": "system",
        "dashboard_summary": {
            "inflow": True,
            "outflow": True,
            "profit_loss": True,
            "budget_used": True,
        },
        "payday_setup_notice_dismissed": False,
    }

    updated = client.patch(
        "/api/v1/settings",
        json={"display_name": "After", "appearance_preference": "dark"},
        headers=csrf_headers(client, registered["csrf_token"]),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "After"
    assert updated.json()["appearance_preference"] == "dark"
    assert "password_hash" not in updated.text


def test_account_currency_can_change_without_financial_data(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.api.settings.create_exchange_rate_service", lambda db, settings: ActiveCurrencyService()
    )
    registered = register(client, "currency@example.test", "Currency User")
    headers = csrf_headers(client, registered["csrf_token"])

    aed = client.patch("/api/v1/settings", json={"currency_code": "aed"}, headers=headers)
    assert aed.status_code == 200, aed.text
    assert aed.json()["currency_code"] == "AED"

    php = client.patch("/api/v1/settings", json={"currency_code": "PHP"}, headers=headers)
    assert php.status_code == 200, php.text
    assert php.json()["currency_code"] == "PHP"


@pytest.mark.parametrize("currency_code", ("ZZZ", "AED!"))
def test_account_currency_rejects_unsupported_or_malformed_code(
    client: TestClient, currency_code: str
) -> None:
    registered = register(client, "invalid-currency@example.test", "Currency User")
    response = client.patch(
        "/api/v1/settings",
        json={"currency_code": currency_code},
        headers=csrf_headers(client, registered["csrf_token"]),
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Value error, Unsupported currency code."


@pytest.mark.parametrize(
    "financial_model",
    (Transaction, BudgetConfiguration, CategoryBudget, CategoryBudgetResetHistory, PaydayAllowance),
)
def test_account_currency_change_is_locked_by_financial_data(
    client: TestClient, db_session: Session, financial_model: type
) -> None:
    registered = register(
        client, f"currency-{financial_model.__tablename__}@example.test", "User"
    )
    user_id = uuid.UUID(registered["user"]["id"])
    category = category_for(db_session, registered["user"]["id"])
    schedule = PaydaySchedule(
        user_id=user_id, first_day=12, second_day=27, effective_from=date(2026, 8, 12)
    )
    if financial_model is Transaction:
        record = Transaction(
            user_id=user_id,
            category_id=category.id,
            transaction_type=category.transaction_type,
            name="Recorded transaction",
            amount_minor=1,
            transaction_date=date(2026, 8, 12),
        )
    elif financial_model is BudgetConfiguration:
        record = BudgetConfiguration(
            user_id=user_id, month_start=date(2026, 8, 1), amount_minor=1
        )
    elif financial_model is CategoryBudget:
        record = CategoryBudget(
            user_id=user_id, category_id=category.id, month_start=date(2026, 8, 1), amount_minor=1
        )
    elif financial_model is CategoryBudgetResetHistory:
        record = CategoryBudgetResetHistory(
            user_id=user_id,
            category_id=category.id,
            period_start=date(2026, 8, 12),
            period_end=date(2026, 8, 26),
            amount_minor=1,
        )
    else:
        db_session.add(schedule)
        db_session.flush()
        record = PaydayAllowance(
            user_id=user_id,
            payday_schedule_id=schedule.id,
            period_start=date(2026, 8, 12),
            amount_minor=1,
        )
    db_session.add(record)
    db_session.commit()

    headers = csrf_headers(client, registered["csrf_token"])
    blocked = client.patch("/api/v1/settings", json={"currency_code": "AED"}, headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "Account currency cannot be changed after financial data exists."

    unchanged = client.patch("/api/v1/settings", json={"currency_code": "PHP"}, headers=headers)
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["currency_code"] == "PHP"


def test_account_currency_lock_is_owner_scoped(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.api.settings.create_exchange_rate_service", lambda db, settings: ActiveCurrencyService()
    )
    first = register(client, "currency-lock-first@example.test", "First")
    first_category = category_for(db_session, first["user"]["id"])
    create_transaction(client, csrf_token=first["csrf_token"], category=first_category)
    second = register(client, "currency-lock-second@example.test", "Second")

    response = client.patch(
        "/api/v1/settings",
        json={"currency_code": "AED"},
        headers=csrf_headers(client, second["csrf_token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["currency_code"] == "AED"


def test_dashboard_summary_preferences_are_owner_scoped_and_persist(client: TestClient) -> None:
    first = register(client, "first-dashboard@example.test", "First")
    updated = client.patch(
        "/api/v1/settings",
        json={
            "dashboard_summary": {
                "inflow": False,
                "outflow": True,
                "profit_loss": False,
                "budget_used": True,
            }
        },
        headers=csrf_headers(client, first["csrf_token"]),
    )
    assert updated.status_code == 200, updated.text

    register(client, "second-dashboard@example.test", "Second")
    second_settings = client.get("/api/v1/settings")
    assert second_settings.json()["dashboard_summary"] == {
        "inflow": True,
        "outflow": True,
        "profit_loss": True,
        "budget_used": True,
    }

    logged_in_again = login(client, "first-dashboard@example.test")
    assert logged_in_again["user"]["display_name"] == "First"
    first_settings = client.get("/api/v1/settings")
    assert first_settings.json()["dashboard_summary"] == {
        "inflow": False,
        "outflow": True,
        "profit_loss": False,
        "budget_used": True,
    }


def test_payday_setup_notice_dismissal_is_owner_scoped_and_persists(client: TestClient) -> None:
    first = register(client, "first-notice@example.test", "First")
    updated = client.patch(
        "/api/v1/settings",
        json={"payday_setup_notice_dismissed": True},
        headers=csrf_headers(client, first["csrf_token"]),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["payday_setup_notice_dismissed"] is True

    register(client, "second-notice@example.test", "Second")
    assert client.get("/api/v1/settings").json()["payday_setup_notice_dismissed"] is False

    login(client, "first-notice@example.test")
    assert client.get("/api/v1/settings").json()["payday_setup_notice_dismissed"] is True


def test_admin_account_management_is_role_guarded_and_never_returns_financial_data(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin_data = register(client, "stage9-admin@example.test", "Administrator")
    target_data = register(client, "stage9-target@example.test", "Target User")
    target_category = category_for(db_session, target_data["user"]["id"])
    db_session.add(
        Transaction(
            user_id=target_category.user_id,
            category_id=target_category.id,
            transaction_type=target_category.transaction_type,
            name="Private financial record",
            amount_minor=123,
            transaction_date=date(2026, 8, 1),
        )
    )
    administrator = db_session.get(User, uuid.UUID(admin_data["user"]["id"]))
    assert administrator is not None
    administrator.role = UserRole.ADMIN
    db_session.commit()

    # Target is currently authenticated, but cannot use any administration API.
    assert client.get("/api/v1/admin/users").status_code == 403
    assert (
        client.post(
            "/api/v1/admin/debug/sentry-error",
            headers=csrf_headers(client, target_data["csrf_token"]),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/admin/users/{target_data['user']['id']}/sessions/revoke",
            headers=csrf_headers(client, target_data["csrf_token"]),
        ).status_code
        == 403
    )

    admin_session = login(client, "stage9-admin@example.test")
    headers = csrf_headers(client, admin_session["csrf_token"])
    captured_errors: list[BaseException] = []
    monkeypatch.setattr("app.api.admin.sentry_sdk.capture_exception", captured_errors.append)
    sentry_test = client.post("/api/v1/admin/debug/sentry-error", headers=headers)
    assert sentry_test.status_code == 204, sentry_test.text
    assert len(captured_errors) == 1
    assert str(captured_errors[0]) == "This is your first backend error!"

    listed = client.get("/api/v1/admin/users")
    assert listed.status_code == 200, listed.text
    target_listing = next(item for item in listed.json() if item["id"] == target_data["user"]["id"])
    assert set(target_listing) == {
        "id",
        "email",
        "display_name",
        "role",
        "is_active",
        "must_change_password",
        "created_at",
    }
    assert "Private financial record" not in listed.text
    assert "password" not in target_listing

    disabled = client.patch(
        f"/api/v1/admin/users/{target_data['user']['id']}/account",
        json={"is_active": False},
        headers=headers,
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["is_active"] is False
    assert (
        client.patch(
            f"/api/v1/admin/users/{admin_data['user']['id']}/account",
            json={"is_active": False},
            headers=headers,
        ).status_code
        == 422
    )

    target = db_session.get(User, uuid.UUID(target_data["user"]["id"]))
    assert target is not None and not target.is_active
    assert db_session.scalar(
        select(AuthSession.id).where(
            AuthSession.user_id == target.id, AuthSession.revoked_at.is_not(None)
        )
    )

    enabled = client.patch(
        f"/api/v1/admin/users/{target.id}/account",
        json={"is_active": True},
        headers=headers,
    )
    assert enabled.status_code == 200
    generated = client.post(f"/api/v1/admin/users/{target.id}/temporary-password", headers=headers)
    assert generated.status_code == 200, generated.text
    temporary_password = generated.json()["temporary_password"]
    assert len(temporary_password) >= 32
    assert "password_hash" not in generated.text
    db_session.expire_all()
    assert db_session.get(User, target.id).must_change_password is True
    audit_events = list(
        db_session.scalars(select(AuditEvent).where(AuditEvent.subject_user_id == target.id))
    )
    assert all(temporary_password not in str(event.metadata_json) for event in audit_events)

    target_login = login(client, "stage9-target@example.test", temporary_password)
    assert client.get("/api/v1/categories").status_code == 403
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": temporary_password, "new_password": "a-new-stage-nine-password"},
        headers=csrf_headers(client, target_login["csrf_token"]),
    )
    assert changed.status_code == 200

    admin_session = login(client, "stage9-admin@example.test")
    headers = csrf_headers(client, admin_session["csrf_token"])
    assert (
        client.post(
            f"/api/v1/admin/users/{target.id}/force-password-change", headers=headers
        ).status_code
        == 204
    )
    assert (
        client.post(f"/api/v1/admin/users/{target.id}/sessions/revoke", headers=headers).status_code
        == 204
    )


def test_admin_legacy_currency_migration_relabels_without_conversion(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.admin.create_exchange_rate_service", lambda db, settings: ActiveCurrencyService())
    admin_data = register(client, "migration-admin@example.test", "Migration Admin")
    target_data = register(client, "migration-target@example.test", "Migration Target")
    target_id = uuid.UUID(target_data["user"]["id"])
    category = category_for(db_session, target_data["user"]["id"])
    legacy = Transaction(
        user_id=target_id,
        category_id=category.id,
        transaction_type=category.transaction_type,
        name="Legacy amount",
        amount_minor=30_000,
        transaction_date=date(2026, 8, 1),
        legacy_currency_record=True,
    )
    budget = BudgetConfiguration(user_id=target_id, month_start=date(2026, 8, 1), amount_minor=55_000)
    allowance_schedule = PaydaySchedule(
        user_id=target_id, first_day=12, second_day=27, effective_from=date(2026, 8, 1)
    )
    db_session.add_all([legacy, budget, allowance_schedule])
    db_session.flush()
    allowance = PaydayAllowance(
        user_id=target_id,
        payday_schedule_id=allowance_schedule.id,
        period_start=date(2026, 8, 12),
        amount_minor=12_000,
    )
    db_session.add(allowance)
    db_session.commit()

    administrator = db_session.get(User, uuid.UUID(admin_data["user"]["id"]))
    assert administrator is not None
    administrator.role = UserRole.ADMIN
    db_session.commit()

    assert client.post(
        f"/api/v1/admin/users/{target_id}/legacy-currency-migration",
        json={"currency_code": "AED", "confirmation": "MIGRATE LEGACY CURRENCY"},
        headers=csrf_headers(client, target_data["csrf_token"]),
    ).status_code == 403
    admin_session = login(client, "migration-admin@example.test")
    response = client.post(
        f"/api/v1/admin/users/{target_id}/legacy-currency-migration",
        json={"currency_code": "AED", "confirmation": "MIGRATE LEGACY CURRENCY"},
        headers=csrf_headers(client, admin_session["csrf_token"]),
    )
    assert response.status_code == 200, response.text
    db_session.expire_all()
    migrated = db_session.get(Transaction, legacy.id)
    assert migrated is not None
    assert migrated.amount_minor == 30_000
    assert migrated.base_amount_minor == 30_000
    assert migrated.currency_code == migrated.base_currency_code == "AED"
    assert str(migrated.exchange_rate) == "1.0000000000"
    assert migrated.exchange_rate_source == "identity"
    assert migrated.exchange_rate_date == migrated.transaction_date
    assert migrated.legacy_currency_record is False
    assert db_session.get(BudgetConfiguration, budget.id).amount_minor == 55_000
    assert db_session.get(PaydayAllowance, allowance.id).amount_minor == 12_000
    preferences = db_session.get(UserPreferences, target_id)
    assert preferences is not None and preferences.currency_code == "AED"
    event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == "admin.legacy_currency_migrated"))
    assert event is not None
    assert event.actor_user_id == administrator.id and event.subject_user_id == target_id
    assert event.metadata_json == {
        "previous_currency_code": "PHP",
        "new_currency_code": "AED",
        "legacy_transactions_migrated": 1,
        "fx_conversion_performed": False,
    }
    assert client.post(
        f"/api/v1/admin/users/{target_id}/legacy-currency-migration",
        json={"currency_code": "PHP", "confirmation": "MIGRATE LEGACY CURRENCY"},
        headers=csrf_headers(client, admin_session["csrf_token"]),
    ).status_code == 409


def test_legacy_currency_migration_rejects_nonlegacy_transactions(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.admin.create_exchange_rate_service", lambda db, settings: ActiveCurrencyService())
    admin_data = register(client, "mixed-admin@example.test", "Mixed Admin")
    target_data = register(client, "mixed-target@example.test", "Mixed Target")
    target_id = uuid.UUID(target_data["user"]["id"])
    category = category_for(db_session, target_data["user"]["id"])
    db_session.add_all([
        Transaction(user_id=target_id, category_id=category.id, transaction_type=category.transaction_type,
                    name="Legacy", amount_minor=100, transaction_date=date(2026, 8, 1), legacy_currency_record=True),
        Transaction(user_id=target_id, category_id=category.id, transaction_type=category.transaction_type,
                    name="New", amount_minor=200, transaction_date=date(2026, 8, 2), legacy_currency_record=False),
    ])
    administrator = db_session.get(User, uuid.UUID(admin_data["user"]["id"]))
    assert administrator is not None
    administrator.role = UserRole.ADMIN
    db_session.commit()
    admin_session = login(client, "mixed-admin@example.test")
    response = client.post(
        f"/api/v1/admin/users/{target_id}/legacy-currency-migration",
        json={"currency_code": "AED", "confirmation": "MIGRATE LEGACY CURRENCY"},
        headers=csrf_headers(client, admin_session["csrf_token"]),
    )
    assert response.status_code == 409
    assert db_session.get(UserPreferences, target_id).currency_code == "PHP"


def test_new_transactions_are_persisted_as_nonlegacy(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "nonlegacy-marker@example.test", "Nonlegacy Marker")
    category = category_for(db_session, registered["user"]["id"])
    created = create_transaction(client, csrf_token=registered["csrf_token"], category=category)
    transaction = db_session.get(Transaction, uuid.UUID(created["id"]))
    assert transaction is not None and transaction.legacy_currency_record is False


def test_legacy_currency_migration_rolls_back_on_commit_failure(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.admin.create_exchange_rate_service", lambda db, settings: ActiveCurrencyService())
    admin_data = register(client, "rollback-admin@example.test", "Rollback Admin")
    target_data = register(client, "rollback-target@example.test", "Rollback Target")
    target_id = uuid.UUID(target_data["user"]["id"])
    category = category_for(db_session, target_data["user"]["id"])
    transaction = Transaction(
        user_id=target_id,
        category_id=category.id,
        transaction_type=category.transaction_type,
        name="Rollback record",
        amount_minor=9_999,
        transaction_date=date(2026, 8, 1),
        legacy_currency_record=True,
    )
    db_session.add(transaction)
    administrator = db_session.get(User, uuid.UUID(admin_data["user"]["id"]))
    assert administrator is not None
    administrator.role = UserRole.ADMIN
    db_session.commit()

    admin_session = login(client, "rollback-admin@example.test")
    original_commit = Session.commit

    def fail_commit(self: Session) -> None:
        raise RuntimeError("forced migration failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="forced migration failure"):
        client.post(
            f"/api/v1/admin/users/{target_id}/legacy-currency-migration",
            json={"currency_code": "AED", "confirmation": "MIGRATE LEGACY CURRENCY"},
            headers=csrf_headers(client, admin_session["csrf_token"]),
        )
    monkeypatch.setattr(Session, "commit", original_commit)
    db_session.expire_all()
    unchanged = db_session.get(Transaction, transaction.id)
    assert unchanged is not None
    assert unchanged.amount_minor == 9_999
    assert unchanged.legacy_currency_record is True
    assert db_session.get(UserPreferences, target_id).currency_code == "PHP"
    assert db_session.scalar(
        select(AuditEvent.id).where(AuditEvent.event_type == "admin.legacy_currency_migrated")
    ) is None


def test_admin_demo_data_is_self_scoped_and_idempotent(
    client: TestClient, db_session: Session
) -> None:
    admin_data = register(client, "demo-admin@example.test", "Demo Administrator")
    other_data = register(client, "demo-user@example.test", "Other User")

    # An ordinary user cannot invoke the debugger action.
    ordinary_headers = csrf_headers(client, other_data["csrf_token"])
    assert (
        client.post("/api/v1/admin/debug/seed-my-account", headers=ordinary_headers).status_code
        == 403
    )

    administrator = db_session.get(User, uuid.UUID(admin_data["user"]["id"]))
    assert administrator is not None
    administrator.role = UserRole.ADMIN
    db_session.commit()
    admin_session = login(client, "demo-admin@example.test")
    headers = csrf_headers(client, admin_session["csrf_token"])

    seeded = client.post("/api/v1/admin/debug/seed-my-account", headers=headers)
    assert seeded.status_code == 200, seeded.text
    assert seeded.json() == {
        "transactions_created": 16,
        "budgets_created": 1,
        "category_budgets_created": 7,
    }

    admin_id = administrator.id
    other_id = uuid.UUID(other_data["user"]["id"])
    assert (
        len(list(db_session.scalars(select(Transaction).where(Transaction.user_id == admin_id))))
        == 16
    )
    assert not list(db_session.scalars(select(Transaction).where(Transaction.user_id == other_id)))
    assert db_session.scalar(
        select(BudgetConfiguration.id).where(BudgetConfiguration.user_id == admin_id)
    )
    assert (
        len(
            list(
                db_session.scalars(select(CategoryBudget).where(CategoryBudget.user_id == admin_id))
            )
        )
        == 7
    )

    dashboard = client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["amount_minor"] == 6_500_000
    assert dashboard.json()["total_inflow_minor"] > 0
    assert dashboard.json()["total_outflow_minor"] > 0
    assert dashboard.json()["category_spending"]

    repeated = client.post("/api/v1/admin/debug/seed-my-account", headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {
        "transactions_created": 0,
        "budgets_created": 0,
        "category_budgets_created": 0,
    }
    assert (
        len(list(db_session.scalars(select(Transaction).where(Transaction.user_id == admin_id))))
        == 16
    )
    assert db_session.scalar(
        select(AuditEvent.id).where(
            AuditEvent.actor_user_id == admin_id,
            AuditEvent.subject_user_id == admin_id,
            AuditEvent.event_type == "admin.demo_data_seeded",
        )
    )

    admin_category = category_of_type(db_session, str(admin_id), TransactionType.OUTFLOW)
    manual = create_transaction(
        client,
        csrf_token=admin_session["csrf_token"],
        category=admin_category,
        name="Keep this manual transaction",
        transaction_date=date.today().isoformat(),
    )
    cleared = client.delete("/api/v1/admin/debug/demo-data", headers=headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {
        "transactions_deleted": 16,
        "budgets_deleted": 1,
        "category_budgets_deleted": 7,
        "allowances_deleted": 0,
        "schedules_deleted": 0,
    }
    assert client.get(f"/api/v1/transactions/{manual['id']}").status_code == 200
    assert not list(
        db_session.scalars(
            select(BudgetConfiguration).where(BudgetConfiguration.user_id == admin_id)
        )
    )
    assert not list(
        db_session.scalars(select(CategoryBudget).where(CategoryBudget.user_id == admin_id))
    )
    cleared_again = client.delete("/api/v1/admin/debug/demo-data", headers=headers)
    assert cleared_again.status_code == 200
    assert cleared_again.json() == {
        "transactions_deleted": 0,
        "budgets_deleted": 0,
        "category_budgets_deleted": 0,
        "allowances_deleted": 0,
        "schedules_deleted": 0,
    }


def test_admin_can_seed_four_completed_cutoff_cycles(
    client: TestClient, db_session: Session
) -> None:
    admin_data = register(client, "cycle-demo-admin@example.test", "Cycle Demo Admin")
    administrator = db_session.get(User, uuid.UUID(admin_data["user"]["id"]))
    assert administrator is not None
    administrator.role = UserRole.ADMIN
    db_session.commit()
    session = login(client, "cycle-demo-admin@example.test")
    headers = csrf_headers(client, session["csrf_token"])

    seeded = client.post("/api/v1/admin/debug/seed-completed-cycles", headers=headers)
    assert seeded.status_code == 200, seeded.text
    assert seeded.json() == {
        "transactions_created": 32,
        "budgets_created": 3,
        "category_budgets_created": 21,
        "schedules_created": 1,
        "allowances_created": 4,
    }
    repeated = client.post("/api/v1/admin/debug/seed-completed-cycles", headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {
        "transactions_created": 0,
        "budgets_created": 0,
        "category_budgets_created": 0,
        "schedules_created": 0,
        "allowances_created": 0,
    }

    allowances = list(
        db_session.scalars(
            select(PaydayAllowance)
            .where(PaydayAllowance.user_id == administrator.id)
            .order_by(PaydayAllowance.period_start)
        )
    )
    assert len(allowances) == 4
    assert all(item.period_start < date.today() for item in allowances)
    assert all(
        (item.payday_schedule.first_day, item.payday_schedule.second_day) == (15, 30)
        for item in allowances
    )

    cleared = client.delete("/api/v1/admin/debug/demo-data", headers=headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {
        "transactions_deleted": 32,
        "budgets_deleted": 3,
        "category_budgets_deleted": 21,
        "allowances_deleted": 4,
        "schedules_deleted": 1,
    }
    assert not list(
        db_session.scalars(
            select(PaydayAllowance).where(PaydayAllowance.user_id == administrator.id)
        )
    )
    assert not list(
        db_session.scalars(select(PaydaySchedule).where(PaydaySchedule.user_id == administrator.id))
    )


def test_regular_user_can_clear_only_their_own_transactions(
    client: TestClient, db_session: Session
) -> None:
    user_a = register(client, "clear-a@example.test", "Clear A")
    category_a = category_for(db_session, user_a["user"]["id"])
    create_transaction(client, csrf_token=user_a["csrf_token"], category=category_a, name="A one")
    create_transaction(client, csrf_token=user_a["csrf_token"], category=category_a, name="A two")

    user_b = register(client, "clear-b@example.test", "Clear B")
    category_b = category_for(db_session, user_b["user"]["id"])
    create_transaction(client, csrf_token=user_b["csrf_token"], category=category_b, name="B one")

    assert client.delete("/api/v1/transactions").status_code == 403
    cleared_b = client.delete(
        "/api/v1/transactions", headers=csrf_headers(client, user_b["csrf_token"])
    )
    assert cleared_b.status_code == 200, cleared_b.text
    assert cleared_b.json() == {"transactions_deleted": 1}
    assert not list(
        db_session.scalars(
            select(Transaction).where(Transaction.user_id == uuid.UUID(user_b["user"]["id"]))
        )
    )
    assert (
        len(
            list(
                db_session.scalars(
                    select(Transaction).where(
                        Transaction.user_id == uuid.UUID(user_a["user"]["id"])
                    )
                )
            )
        )
        == 2
    )

    session_a = login(client, "clear-a@example.test")
    cleared_a = client.delete(
        "/api/v1/transactions", headers=csrf_headers(client, session_a["csrf_token"])
    )
    assert cleared_a.status_code == 200
    assert cleared_a.json() == {"transactions_deleted": 2}
    event = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.actor_user_id == uuid.UUID(user_a["user"]["id"]),
            AuditEvent.event_type == "transaction.all_deleted",
        )
    )
    assert event is not None
    assert event.metadata_json == {"deleted_count": 2}


def test_bulk_delete_is_atomic_and_owner_scoped(client: TestClient, db_session: Session) -> None:
    user_a = register(client, "bulk-a@example.test", "Bulk A")
    category_a = category_for(db_session, user_a["user"]["id"])
    first = create_transaction(
        client, csrf_token=user_a["csrf_token"], category=category_a, name="First selected"
    )
    second = create_transaction(
        client, csrf_token=user_a["csrf_token"], category=category_a, name="Second selected"
    )

    user_b = register(client, "bulk-b@example.test", "Bulk B")
    category_b = category_for(db_session, user_b["user"]["id"])
    other = create_transaction(
        client, csrf_token=user_b["csrf_token"], category=category_b, name="Keep mine"
    )
    headers_b = csrf_headers(client, user_b["csrf_token"])

    rejected = client.request(
        "DELETE",
        "/api/v1/transactions/bulk",
        json={"transaction_ids": [first["id"], other["id"]]},
        headers=headers_b,
    )
    assert rejected.status_code == 404
    assert client.get(f"/api/v1/transactions/{other['id']}").status_code == 200

    session_a = login(client, "bulk-a@example.test")
    deleted = client.request(
        "DELETE",
        "/api/v1/transactions/bulk",
        json={"transaction_ids": [first["id"], second["id"]]},
        headers=csrf_headers(client, session_a["csrf_token"]),
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"transactions_deleted": 2}
    assert client.get(f"/api/v1/transactions/{first['id']}").status_code == 404
    assert client.get(f"/api/v1/transactions/{second['id']}").status_code == 404


def test_login_rate_limit_uses_generic_failure_message(client: TestClient) -> None:
    for _ in range(2):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.test", "password": "wrong-password"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password."
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.test", "password": "wrong-password"},
        ).status_code
        == 429
    )


def test_transactions_validate_category_type_owner_and_historical_dates(
    client: TestClient, db_session: Session
) -> None:
    user_a = register(client, "transactions-a@example.test", "Transaction User A")
    category_a = category_for(db_session, user_a["user"]["id"])
    user_b = register(client, "transactions-b@example.test", "Transaction User B")
    category_b = category_for(db_session, user_b["user"]["id"])

    login(client, "transactions-a@example.test")
    headers = csrf_headers(client, client.cookies.get("cashbook_csrf") or user_a["csrf_token"])
    foreign_category = client.post(
        "/api/v1/transactions",
        json={
            "name": "Not mine",
            "transaction_type": category_b.transaction_type.value,
            "category_id": str(category_b.id),
            "amount_minor": 1,
            "transaction_date": "2024-02-29",
        },
        headers=headers,
    )
    assert foreign_category.status_code == 422

    invalid_amount = client.post(
        "/api/v1/transactions",
        json={
            "name": "Invalid amount",
            "transaction_type": category_a.transaction_type.value,
            "category_id": str(category_a.id),
            "amount_minor": 0,
            "transaction_date": "2024-02-29",
        },
        headers=headers,
    )
    assert invalid_amount.status_code == 422

    historical = create_transaction(
        client,
        csrf_token=client.cookies.get("cashbook_csrf") or user_a["csrf_token"],
        category=category_a,
        name="Leap day rent",
        amount_minor=25_000,
        transaction_date="2024-02-29",
        notes="Historical record",
    )
    assert historical["transaction_date"] == "2024-02-29"
    assert historical["amount_minor"] == 25_000
    assert historical["category_id"] == str(category_a.id)


def test_transaction_listing_filters_search_sort_and_pagination(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "transaction-list@example.test", "List User")
    category = category_for(db_session, registered["user"]["id"])
    inflow_category = db_session.scalar(
        select(Category).where(
            Category.user_id == category.user_id,
            Category.transaction_type == TransactionType.INFLOW,
        )
    )
    assert inflow_category is not None
    headers = csrf_headers(client, registered["csrf_token"])
    first = create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=category,
        name="January food",
        transaction_date="2025-01-10",
        notes="market",
    )
    second = create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=category,
        name="February food",
        transaction_date="2025-02-10",
        notes="groceries",
    )
    create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=inflow_category,
        name="February income",
        transaction_date="2025-02-15",
    )
    newest = client.get("/api/v1/transactions?page=1&page_size=1&sort=newest")
    assert newest.status_code == 200
    assert newest.json()["total"] == 3
    assert newest.json()["total_pages"] == 3
    assert newest.json()["items"][0]["transaction_type"] == "inflow"
    # The latest row retains its chronological balance even when displayed
    # newest-first: -1250 -1250 +1250 = -1250.
    assert newest.json()["items"][0]["running_balance_minor"] == -1_250

    filtered = client.get(
        f"/api/v1/transactions?date_from=2025-01-01&date_to=2025-01-31&category_id={category.id}&search=market&sort=oldest"
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [first["id"]]
    # Filtering to January must not restart the balance at zero.
    assert filtered.json()["items"][0]["running_balance_minor"] == -1_250
    type_filtered = client.get("/api/v1/transactions?transaction_type=outflow")
    assert type_filtered.status_code == 200
    assert {item["id"] for item in type_filtered.json()["items"]} == {first["id"], second["id"]}
    assert (
        client.get("/api/v1/transactions?date_from=2025-02-01&date_to=2025-01-01").status_code
        == 422
    )
    assert headers["X-CSRF-Token"]


def test_statement_payday_grouping_uses_effective_historical_schedule(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "statement-payday@example.test", "Statement User")
    headers = csrf_headers(client, registered["csrf_token"])
    category = category_of_type(db_session, registered["user"]["id"], TransactionType.OUTFLOW)
    schedule = client.post(
        "/api/v1/budget-settings/payday-schedules",
        json={"first_day": 12, "second_day": 27, "effective_from": "2024-12-27"},
        headers=headers,
    )
    assert schedule.status_code == 201, schedule.text
    transaction = create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=category,
        name="Cross-month statement row",
        amount_minor=500,
        transaction_date="2025-02-05",
    )

    statement = client.get("/api/v1/transactions?grouping=payday&sort=oldest")
    assert statement.status_code == 200, statement.text
    row = next(item for item in statement.json()["items"] if item["id"] == transaction["id"])
    assert row["period_start"] == "2025-01-27"
    assert row["period_end"] == "2025-02-11"
    assert row["running_balance_minor"] == -500


def test_transaction_update_delete_and_cross_user_access_are_owner_scoped(
    client: TestClient, db_session: Session
) -> None:
    user_a = register(client, "transaction-owner-a@example.test", "Owner A")
    category_a = category_for(db_session, user_a["user"]["id"])
    transaction = create_transaction(
        client,
        csrf_token=user_a["csrf_token"],
        category=category_a,
        name="Original",
        amount_minor=500,
        transaction_date="2025-12-31",
    )
    user_b = register(client, "transaction-owner-b@example.test", "Owner B")

    login(client, "transaction-owner-a@example.test")
    headers_a = csrf_headers(client, client.cookies.get("cashbook_csrf") or user_a["csrf_token"])
    updated = client.patch(
        f"/api/v1/transactions/{transaction['id']}",
        json={"name": "Corrected", "amount_minor": 750, "notes": "updated"},
        headers=headers_a,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Corrected"
    assert updated.json()["amount_minor"] == 750
    assert updated.json()["notes"] == "updated"

    login(client, "transaction-owner-b@example.test")
    headers_b = csrf_headers(client, client.cookies.get("cashbook_csrf") or user_b["csrf_token"])
    assert client.get(f"/api/v1/transactions/{transaction['id']}").status_code == 404
    assert (
        client.patch(
            f"/api/v1/transactions/{transaction['id']}", json={"name": "Stolen"}, headers=headers_b
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/transactions/{transaction['id']}", headers=headers_b).status_code
        == 404
    )

    login(client, "transaction-owner-a@example.test")
    deleted = client.delete(
        f"/api/v1/transactions/{transaction['id']}",
        headers=csrf_headers(client, client.cookies.get("cashbook_csrf") or user_a["csrf_token"]),
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/transactions/{transaction['id']}").status_code == 404


def test_transaction_currency_create_update_and_running_balance(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = register(client, "transaction-fx@example.test", "FX User")
    category = category_of_type(
        db_session, registered["user"]["id"], TransactionType.OUTFLOW
    )
    first_date = date(2026, 8, 1)
    second_date = date(2026, 8, 2)
    service = StubExchangeRateService(
        {
            ("AED", "PHP", first_date): Decimal("16.5666"),
            ("AED", "PHP", second_date): Decimal("16.7000"),
        }
    )
    monkeypatch.setattr(
        "app.api.transactions.create_exchange_rate_service", lambda db, settings: service
    )

    identity = create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=category,
        amount_minor=1_000,
    )
    assert identity["currency_code"] == identity["base_currency_code"] == "PHP"
    assert identity["base_amount_minor"] == 1_000
    assert identity["exchange_rate"] == "1.0000000000"
    assert identity["exchange_rate_source"] == "identity"
    assert service.calls == []

    foreign = create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=category,
        amount_minor=10_000,
        currency_code="aed",
    )
    assert foreign["amount_minor"] == 10_000
    assert foreign["currency_code"] == "AED"
    assert foreign["base_amount_minor"] == 165_666
    original_snapshot = {
        key: foreign[key]
        for key in (
            "base_amount_minor",
            "base_currency_code",
            "exchange_rate",
            "exchange_rate_date",
            "exchange_rate_source",
        )
    }

    headers = csrf_headers(client, registered["csrf_token"])
    metadata_edit = client.patch(
        f"/api/v1/transactions/{foreign['id']}",
        json={"notes": "preserve the snapshot"},
        headers=headers,
    )
    assert metadata_edit.status_code == 200, metadata_edit.text
    assert {key: metadata_edit.json()[key] for key in original_snapshot} == original_snapshot
    assert len(service.calls) == 1

    financial_edit = client.patch(
        f"/api/v1/transactions/{foreign['id']}",
        json={"amount_minor": 20_000, "currency_code": "AED", "transaction_date": "2026-08-02"},
        headers=headers,
    )
    assert financial_edit.status_code == 200, financial_edit.text
    assert financial_edit.json()["base_amount_minor"] == 334_000
    assert financial_edit.json()["exchange_rate_date"] == "2026-08-02"
    assert len(service.calls) == 2

    statement = client.get("/api/v1/transactions?sort=oldest")
    assert statement.status_code == 200, statement.text
    assert statement.json()["items"][-1]["running_balance_minor"] == -335_000


def test_account_summaries_use_frozen_base_amounts_for_foreign_transactions(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = register(client, "base-summary@example.test", "Base Summary")
    headers = csrf_headers(client, registered["csrf_token"])
    outflow = category_of_type(db_session, registered["user"]["id"], TransactionType.OUTFLOW)
    inflow = category_of_type(db_session, registered["user"]["id"], TransactionType.INFLOW)
    transaction_date = date(2026, 8, 12)
    service = StubExchangeRateService({("AED", "PHP", transaction_date): Decimal("16.5")})
    monkeypatch.setattr(
        "app.api.transactions.create_exchange_rate_service", lambda db, settings: service
    )

    create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=inflow,
        amount_minor=1_000_000,
        transaction_date="2026-08-12",
    )
    foreign = create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=outflow,
        amount_minor=10_000,
        currency_code="AED",
        transaction_date="2026-08-12",
    )
    assert foreign["base_amount_minor"] == 165_000
    assert client.put(
        "/api/v1/budgets/2026-08-01", json={"amount_minor": 200_000}, headers=headers
    ).status_code == 200
    assert client.put(
        f"/api/v1/budgets/2026-08-01/categories/{outflow.id}",
        json={"amount_minor": 180_000},
        headers=headers,
    ).status_code == 200
    assert client.post(
        "/api/v1/budget-settings/payday-schedules",
        json={"first_day": 12, "second_day": 27, "effective_from": "2026-08-12"},
        headers=headers,
    ).status_code == 201
    allowance = client.put(
        "/api/v1/budgets/2026-08-01/allowances/2026-08-12",
        json={"amount_minor": 200_000},
        headers=headers,
    )
    assert allowance.status_code == 200
    assert allowance.json()["used_minor"] == 165_000
    assert allowance.json()["remaining_minor"] == 35_000

    dashboard = client.get("/api/v1/dashboard?anchor_date=2026-08-12&period_mode=calendar_month")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["base_currency_code"] == "PHP"
    assert dashboard.json()["total_inflow_minor"] == 1_000_000
    assert dashboard.json()["total_outflow_minor"] == 165_000
    assert dashboard.json()["net_profit_loss_minor"] == 835_000
    assert dashboard.json()["used_minor"] == 165_000
    assert dashboard.json()["remaining_minor"] == 35_000
    assert dashboard.json()["category_spending"][0]["used_minor"] == 165_000
    assert dashboard.json()["category_budgets"][0]["remaining_minor"] == 15_000

    payday = client.get("/api/v1/dashboard?anchor_date=2026-08-12&period_mode=payday")
    assert payday.status_code == 200
    assert payday.json()["total_outflow_minor"] == 165_000
    assert payday.json()["remaining_minor"] == 35_000
    cycle = client.get("/api/v1/budgets/2026-08-01")
    assert cycle.status_code == 200
    assert cycle.json()["total_outflow_minor"] == 165_000
    assert cycle.json()["category_budgets"][0]["used_minor"] == 165_000
    assert cycle.json()["payday_allowances"][0]["used_minor"] == 165_000
    statement = client.get("/api/v1/transactions?sort=oldest")
    assert statement.status_code == 200
    assert statement.json()["items"][-1]["running_balance_minor"] == 835_000


def test_failed_fx_update_leaves_transaction_unchanged(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.exchange_rates import ExchangeRateProviderError

    registered = register(client, "transaction-fx-failure@example.test", "FX Failure")
    category = category_for(db_session, registered["user"]["id"])
    transaction = create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=category,
        amount_minor=500,
    )

    class FailingService:
        def is_available_for_new_selection(self, currency_code: str) -> bool:
            return True

        def get_exchange_rate(self, source, target, requested_date):
            raise ExchangeRateProviderError("provider internals")

    monkeypatch.setattr(
        "app.api.transactions.create_exchange_rate_service",
        lambda db, settings: FailingService(),
    )
    invalid = client.post(
        "/api/v1/transactions",
        json={
            "name": "Unsupported",
            "transaction_type": category.transaction_type.value,
            "category_id": str(category.id),
            "amount_minor": 100,
            "currency_code": "ZZZ",
        },
        headers=csrf_headers(client, registered["csrf_token"]),
    )
    assert invalid.status_code == 422
    failed_create = client.post(
        "/api/v1/transactions",
        json={
            "name": "Not persisted",
            "transaction_type": category.transaction_type.value,
            "category_id": str(category.id),
            "amount_minor": 100,
            "currency_code": "AED",
            "transaction_date": "2026-08-01",
        },
        headers=csrf_headers(client, registered["csrf_token"]),
    )
    assert failed_create.status_code == 503
    assert db_session.scalar(select(Transaction).where(Transaction.name == "Not persisted")) is None
    response = client.patch(
        f"/api/v1/transactions/{transaction['id']}",
        json={"amount_minor": 900, "currency_code": "AED"},
        headers=csrf_headers(client, registered["csrf_token"]),
    )
    assert response.status_code == 503
    assert "provider internals" not in response.text
    persisted = client.get(f"/api/v1/transactions/{transaction['id']}").json()
    assert persisted["amount_minor"] == 500
    assert persisted["currency_code"] == "PHP"


def test_aed_account_identity_and_php_transaction_conversion(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = register(client, "transaction-aed-base@example.test", "AED Base")
    preferences = db_session.get(UserPreferences, uuid.UUID(registered["user"]["id"]))
    assert preferences is not None
    preferences.currency_code = "AED"
    db_session.commit()
    category = category_for(db_session, registered["user"]["id"])
    service = StubExchangeRateService(
        {("PHP", "AED", date(2026, 8, 1)): Decimal("0.0603646")}
    )
    monkeypatch.setattr(
        "app.api.transactions.create_exchange_rate_service", lambda db, settings: service
    )
    identity = create_transaction(
        client, csrf_token=registered["csrf_token"], category=category, amount_minor=1_000
    )
    assert identity["currency_code"] == identity["base_currency_code"] == "AED"
    foreign = create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=category,
        amount_minor=1_656,
        currency_code="PHP",
    )
    assert foreign["base_currency_code"] == "AED"
    assert foreign["base_amount_minor"] == 100


def test_budget_configuration_uses_outflows_and_reports_subdivision_warnings(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "budget@example.test", "Budget User")
    headers = csrf_headers(client, registered["csrf_token"])
    outflow = category_of_type(db_session, registered["user"]["id"], TransactionType.OUTFLOW)
    inflow = category_of_type(db_session, registered["user"]["id"], TransactionType.INFLOW)
    create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=outflow,
        amount_minor=12_000,
        transaction_date="2026-08-12",
    )
    create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=inflow,
        amount_minor=50_000,
        transaction_date="2026-08-13",
    )

    budget = client.put(
        "/api/v1/budgets/2026-08-01", json={"amount_minor": 30_000}, headers=headers
    )
    assert budget.status_code == 200, budget.text
    assert budget.json()["total_inflow_minor"] == 50_000
    assert budget.json()["used_minor"] == 12_000
    assert budget.json()["remaining_minor"] == 18_000
    assert budget.json()["allowances_match_budget"] is False
    unavailable_payday = client.put(
        "/api/v1/budget-settings", json={"reporting_mode": "payday"}, headers=headers
    )
    assert unavailable_payday.status_code == 422
    schedule = client.post(
        "/api/v1/budget-settings/payday-schedules",
        json={"first_day": 12, "second_day": 27, "effective_from": "2026-08-12"},
        headers=headers,
    )
    assert schedule.status_code == 201, schedule.text
    reporting_mode = client.put(
        "/api/v1/budget-settings", json={"reporting_mode": "payday"}, headers=headers
    )
    assert reporting_mode.status_code == 200
    assert reporting_mode.json()["reporting_mode"] == "payday"
    for period_start, amount in (("2026-08-12", 15_000), ("2026-08-27", 15_000)):
        response = client.put(
            f"/api/v1/budgets/2026-08-01/allowances/{period_start}",
            json={"amount_minor": amount},
            headers=headers,
        )
        assert response.status_code == 200, response.text
    category_budget = client.put(
        f"/api/v1/budgets/2026-08-01/categories/{outflow.id}",
        json={"amount_minor": 10_000},
        headers=headers,
    )
    assert category_budget.status_code == 200
    assert category_budget.json()["remaining_minor"] == -2_000
    assert category_budget.json()["is_overspent"] is True

    cycle = client.get("/api/v1/budgets/2026-08-01")
    assert cycle.status_code == 200
    assert cycle.json()["allowances_total_minor"] == 30_000
    assert cycle.json()["allowances_match_budget"] is True
    assert cycle.json()["reporting_mode"] == "payday"
    assert cycle.json()["payday_allowances"][0]["used_minor"] == 12_000


def test_payday_schedule_versions_preserve_historical_periods_and_budget_records(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "schedule-history@example.test", "Schedule History")
    headers = csrf_headers(client, registered["csrf_token"])
    outflow = category_of_type(db_session, registered["user"]["id"], TransactionType.OUTFLOW)
    assert (
        client.post(
            "/api/v1/budget-settings/payday-schedules",
            json={"first_day": 12, "second_day": 27, "effective_from": "2026-08-12"},
            headers=headers,
        ).status_code
        == 201
    )
    first = client.put(
        "/api/v1/budgets/2026-08-01",
        json={"amount_minor": 20_000},
        headers=headers,
    )
    assert first.status_code == 200
    historical_transaction = create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=outflow,
        amount_minor=5_000,
        transaction_date="2026-08-13",
    )
    newer = client.post(
        "/api/v1/budget-settings/payday-schedules",
        json={"first_day": 15, "second_day": 28, "effective_from": "2026-09-15"},
        headers=headers,
    )
    assert newer.status_code == 201, newer.text
    historical = client.get("/api/v1/budgets/2026-08-01")
    assert historical.status_code == 200
    assert historical.json()["amount_minor"] == 20_000
    assert historical.json()["used_minor"] == 5_000
    assert historical.json()["payday_schedule"]["first_day"] == 12
    corrected = client.patch(
        f"/api/v1/transactions/{historical_transaction['id']}",
        json={"amount_minor": 7_000},
        headers=headers,
    )
    assert corrected.status_code == 200
    assert client.get("/api/v1/budgets/2026-08-01").json()["used_minor"] == 7_000
    september = client.get("/api/v1/budgets/2026-09-01")
    assert september.json()["payday_schedule"]["first_day"] == 15


def test_budget_endpoints_are_owner_scoped_and_validate_boundaries(
    client: TestClient, db_session: Session
) -> None:
    user_a = register(client, "budget-a@example.test", "Budget A")
    outflow_a = category_of_type(db_session, user_a["user"]["id"], TransactionType.OUTFLOW)
    headers_a = csrf_headers(client, user_a["csrf_token"])
    assert (
        client.put(
            "/api/v1/budgets/2026-08-02", json={"amount_minor": 1}, headers=headers_a
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/budgets/2026-08-01/allowances/2026-08-12",
            json={"amount_minor": 1},
            headers=headers_a,
        ).status_code
        == 422
    )
    user_b = register(client, "budget-b@example.test", "Budget B")
    login(client, "budget-b@example.test")
    headers_b = csrf_headers(client, client.cookies.get("cashbook_csrf") or user_b["csrf_token"])
    assert (
        client.put(
            f"/api/v1/budgets/2026-08-01/categories/{outflow_a.id}",
            json={"amount_minor": 1},
            headers=headers_b,
        ).status_code
        == 422
    )
    assert client.get("/api/v1/budgets/2026-08-01").json()["amount_minor"] is None


def test_payday_allowance_uses_every_transaction_in_a_cross_month_segment(
    client: TestClient, db_session: Session
) -> None:
    registered = register(client, "payday-span@example.test", "Payday Span")
    headers = csrf_headers(client, registered["csrf_token"])
    assert (
        client.put(
            "/api/v1/budgets/2026-08-01", json={"amount_minor": 10_000}, headers=headers
        ).status_code
        == 200
    )
    schedule = client.post(
        "/api/v1/budget-settings/payday-schedules",
        json={"first_day": 12, "second_day": 27, "effective_from": "2026-08-12"},
        headers=headers,
    )
    assert schedule.status_code == 201, schedule.text
    allowance = client.put(
        "/api/v1/budgets/2026-08-01/allowances/2026-08-27",
        json={"amount_minor": 4_000},
        headers=headers,
    )
    assert allowance.status_code == 200, allowance.text
    outflow = category_of_type(db_session, registered["user"]["id"], TransactionType.OUTFLOW)
    create_transaction(
        client,
        csrf_token=registered["csrf_token"],
        category=outflow,
        amount_minor=1_200,
        transaction_date="2026-09-01",
    )

    cycle = client.get("/api/v1/budgets/2026-08-01")
    assert cycle.status_code == 200, cycle.text
    august_27 = next(
        item for item in cycle.json()["payday_allowances"] if item["period_start"] == "2026-08-27"
    )
    assert august_27["used_minor"] == 1_200
    assert august_27["remaining_minor"] == 2_800


def test_payday_schedule_change_may_start_at_its_new_schedule_boundary(client: TestClient) -> None:
    registered = register(client, "payday-history@example.test", "Payday History")
    headers = csrf_headers(client, registered["csrf_token"])
    initial = client.post(
        "/api/v1/budget-settings/payday-schedules",
        json={"first_day": 12, "second_day": 27, "effective_from": "2026-07-12"},
        headers=headers,
    )
    assert initial.status_code == 201, initial.text
    changed = client.post(
        "/api/v1/budget-settings/payday-schedules",
        json={"first_day": 15, "second_day": 28, "effective_from": "2026-08-15"},
        headers=headers,
    )
    assert changed.status_code == 201, changed.text
