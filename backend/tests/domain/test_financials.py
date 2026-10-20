from decimal import Decimal

import pytest

from app.domain.financials import (
    CashFlowType,
    FinancialEntry,
    allowance_total_matches_budget,
    calculate_budget_allocation,
    calculate_financial_summary,
)


def test_financial_summary_excludes_inflow_from_spending_budget() -> None:
    summary = calculate_financial_summary(
        [
            FinancialEntry(CashFlowType.INFLOW, 50_000),
            FinancialEntry(CashFlowType.OUTFLOW, 12_345),
            FinancialEntry(CashFlowType.OUTFLOW, 7_655),
        ],
        budget_minor=30_000,
    )

    assert summary.total_inflow_minor == 50_000
    assert summary.total_outflow_minor == 20_000
    assert summary.net_profit_loss_minor == 30_000
    assert summary.budget_used_minor == 20_000
    assert summary.budget_remaining_minor == 10_000
    assert summary.budget_usage_percent == Decimal("66.66666666666666666666666667")


@pytest.mark.parametrize("base_amount_minor", [1_650, 1_650_000])
def test_base_currency_minor_units_are_aggregated_without_exponent_assumptions(
    base_amount_minor: int,
) -> None:
    summary = calculate_financial_summary(
        [FinancialEntry(CashFlowType.OUTFLOW, base_amount_minor)],
        budget_minor=base_amount_minor * 2,
    )
    assert summary.total_outflow_minor == base_amount_minor
    assert summary.budget_remaining_minor == base_amount_minor


def test_missing_budget_has_no_remaining_or_usage_percentage() -> None:
    summary = calculate_financial_summary(
        [FinancialEntry(CashFlowType.OUTFLOW, 1)], budget_minor=None
    )

    assert summary.budget_remaining_minor is None
    assert summary.budget_usage_percent is None


def test_zero_budget_does_not_divide_by_zero() -> None:
    summary = calculate_financial_summary(
        [FinancialEntry(CashFlowType.OUTFLOW, 100)], budget_minor=0
    )

    assert summary.budget_remaining_minor == -100
    assert summary.budget_usage_percent is None


@pytest.mark.parametrize("amount", [0, -1])
def test_nonpositive_transaction_amount_is_rejected(amount: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        calculate_financial_summary([FinancialEntry(CashFlowType.INFLOW, amount)], budget_minor=0)


def test_negative_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        calculate_financial_summary([], budget_minor=-1)


def test_category_or_payday_allocation_counts_only_outflows_and_allows_overspending() -> None:
    allocation = calculate_budget_allocation(
        [
            FinancialEntry(CashFlowType.INFLOW, 90_000),
            FinancialEntry(CashFlowType.OUTFLOW, 7_500),
            FinancialEntry(CashFlowType.OUTFLOW, 3_000),
        ],
        allocation_minor=10_000,
    )
    assert allocation.used_minor == 10_500
    assert allocation.remaining_minor == -500
    assert allocation.is_overspent is True
    assert allocation.usage_percent == Decimal("105")


def test_unconfigured_allocation_is_not_treated_as_zero() -> None:
    allocation = calculate_budget_allocation(
        [FinancialEntry(CashFlowType.OUTFLOW, 500)], allocation_minor=None
    )
    assert allocation.remaining_minor is None
    assert allocation.is_overspent is False


def test_allowance_warning_detects_missing_or_overallocated_subdivisions() -> None:
    assert allowance_total_matches_budget([4_000, 6_000], 10_000) is True
    assert allowance_total_matches_budget([4_000, 7_000], 10_000) is False
    assert allowance_total_matches_budget([], None) is None


def test_negative_allowance_is_rejected() -> None:
    with pytest.raises(ValueError, match="allowance"):
        allowance_total_matches_budget([-1], 100)
