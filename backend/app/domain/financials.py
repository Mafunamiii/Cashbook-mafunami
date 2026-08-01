"""Pure integer-minor-unit financial summary calculations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class CashFlowType(StrEnum):
    INFLOW = "inflow"
    OUTFLOW = "outflow"


@dataclass(frozen=True)
class FinancialEntry:
    transaction_type: CashFlowType
    amount_minor: int


@dataclass(frozen=True)
class FinancialSummary:
    total_inflow_minor: int
    total_outflow_minor: int
    net_profit_loss_minor: int
    budget_minor: int | None
    budget_used_minor: int
    budget_remaining_minor: int | None
    budget_usage_percent: Decimal | None


@dataclass(frozen=True)
class BudgetAllocationSummary:
    """Usage of a non-additive subdivision of an overall budget."""

    allocation_minor: int | None
    used_minor: int
    remaining_minor: int | None
    usage_percent: Decimal | None
    is_overspent: bool


def calculate_financial_summary(
    entries: Iterable[FinancialEntry], budget_minor: int | None
) -> FinancialSummary:
    """Calculate a summary without floats or database dependencies.

    ``budget_minor`` may be absent.  A zero budget has a defined remaining
    amount but no percentage, avoiding a divide-by-zero display value.
    """
    if budget_minor is not None and budget_minor < 0:
        raise ValueError("budget_minor cannot be negative")

    inflow = 0
    outflow = 0
    for entry in entries:
        if entry.amount_minor <= 0:
            raise ValueError("transaction amounts must be positive")
        if entry.transaction_type is CashFlowType.INFLOW:
            inflow += entry.amount_minor
        elif entry.transaction_type is CashFlowType.OUTFLOW:
            outflow += entry.amount_minor
        else:  # Defensive for values supplied outside the enum type.
            raise ValueError("unknown transaction type")

    remaining = None if budget_minor is None else budget_minor - outflow
    usage_percent = (
        None
        if budget_minor in (None, 0)
        else (Decimal(outflow) * Decimal("100")) / Decimal(budget_minor)
    )
    return FinancialSummary(
        total_inflow_minor=inflow,
        total_outflow_minor=outflow,
        net_profit_loss_minor=inflow - outflow,
        budget_minor=budget_minor,
        budget_used_minor=outflow,
        budget_remaining_minor=remaining,
        budget_usage_percent=usage_percent,
    )


def calculate_budget_allocation(
    entries: Iterable[FinancialEntry], allocation_minor: int | None
) -> BudgetAllocationSummary:
    """Calculate an allowance or category allocation using outflows only.

    Allocations are explicitly subdivisions: incoming money is included in
    neither their used amount nor their remaining amount.  ``None`` means no
    allocation has been configured, not a zero allocation.
    """
    if allocation_minor is not None and allocation_minor < 0:
        raise ValueError("allocation_minor cannot be negative")

    used = 0
    for entry in entries:
        if entry.amount_minor <= 0:
            raise ValueError("transaction amounts must be positive")
        if entry.transaction_type is CashFlowType.OUTFLOW:
            used += entry.amount_minor
        elif entry.transaction_type is not CashFlowType.INFLOW:
            raise ValueError("unknown transaction type")

    remaining = None if allocation_minor is None else allocation_minor - used
    usage_percent = (
        None
        if allocation_minor in (None, 0)
        else (Decimal(used) * Decimal("100")) / Decimal(allocation_minor)
    )
    return BudgetAllocationSummary(
        allocation_minor=allocation_minor,
        used_minor=used,
        remaining_minor=remaining,
        usage_percent=usage_percent,
        is_overspent=allocation_minor is not None and used > allocation_minor,
    )


def allowance_total_matches_budget(
    allowance_amounts_minor: Iterable[int], overall_budget_minor: int | None
) -> bool | None:
    """Return whether configured segment allocations equal an overall budget.

    ``None`` means no overall budget exists, so no mismatch warning should be
    shown.  Negative values are invalid even though an allowance of zero is a
    supported deliberate choice.
    """
    amounts = list(allowance_amounts_minor)
    if any(amount < 0 for amount in amounts):
        raise ValueError("allowance amounts cannot be negative")
    if overall_budget_minor is None:
        return None
    if overall_budget_minor < 0:
        raise ValueError("overall_budget_minor cannot be negative")
    return sum(amounts) == overall_budget_minor
