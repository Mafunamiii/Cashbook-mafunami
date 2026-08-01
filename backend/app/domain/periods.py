"""Calendar and payday reporting-period calculations."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ReportingPeriod:
    start: date
    end: date


def calendar_month_period(value: date) -> ReportingPeriod:
    """Return the inclusive calendar month containing ``value``."""
    last_day = monthrange(value.year, value.month)[1]
    return ReportingPeriod(
        date(value.year, value.month, 1), date(value.year, value.month, last_day)
    )


def effective_payday(year: int, month: int, cutoff_day: int) -> date:
    """Clamp a configured cutoff day to the final calendar day of its month."""
    _validate_cutoff_day(cutoff_day)
    return date(year, month, min(cutoff_day, monthrange(year, month)[1]))


def payday_period(value: date, first_day: int, second_day: int) -> ReportingPeriod:
    """Return the inclusive recurring-payday period containing ``value``.

    The schedule must contain two ascending nominal days.  If clamping makes
    both dates coincide (for example 30 and 31 in February), the later nominal
    cutoff owns that date and the duplicate boundary is discarded.  This avoids
    creating a zero-length reporting period.
    """
    _validate_schedule(first_day, second_day)
    cutoffs = _surrounding_effective_paydays(value, first_day, second_day)
    start = max(cutoff for cutoff in cutoffs if cutoff <= value)
    end = min(cutoff for cutoff in cutoffs if cutoff > start) - timedelta(days=1)
    return ReportingPeriod(start=start, end=end)


def transaction_period(transaction_date: date, first_day: int, second_day: int) -> ReportingPeriod:
    """Assign a transaction's local calendar date to its payday period."""
    return payday_period(transaction_date, first_day, second_day)


def versioned_payday_period(
    value: date, schedule_versions: Iterable[tuple[date, int, int]]
) -> ReportingPeriod:
    """Return a payday period across immutable, effective-dated schedules.

    A newer configuration can begin on a boundary that differs from the
    preceding configuration.  The preceding period then ends the day before
    that newer configuration takes effect, so reports never overlap periods.
    """
    versions = sorted(schedule_versions, key=lambda item: item[0])
    active = [version for version in versions if version[0] <= value]
    if not active:
        raise ValueError("no payday schedule is effective for this date")
    _, first_day, second_day = active[-1]
    period = payday_period(value, first_day, second_day)
    next_effective = min(
        (effective_from for effective_from, _, _ in versions if effective_from > period.start),
        default=None,
    )
    if next_effective is None or next_effective > period.end:
        return period
    return ReportingPeriod(start=period.start, end=next_effective - timedelta(days=1))


def payday_periods_starting_in_month(
    month_start: date, first_day: int, second_day: int
) -> list[ReportingPeriod]:
    """Return the distinct payday periods whose starts occur in ``month_start``'s month.

    The result is useful for validating a calendar month's configured payday
    allowances.  Nominal cutoffs that clamp to the same date are deduplicated,
    matching :func:`payday_period`.
    """
    if month_start.day != 1:
        raise ValueError("month_start must be the first day of a month")
    _validate_schedule(first_day, second_day)
    starts = {
        effective_payday(month_start.year, month_start.month, first_day),
        effective_payday(month_start.year, month_start.month, second_day),
    }
    return [payday_period(start, first_day, second_day) for start in sorted(starts)]


def _surrounding_effective_paydays(value: date, first_day: int, second_day: int) -> list[date]:
    cutoffs: set[date] = set()
    for year, month in _months_around(value.year, value.month):
        cutoffs.add(effective_payday(year, month, first_day))
        cutoffs.add(effective_payday(year, month, second_day))
    return sorted(cutoffs)


def _months_around(year: int, month: int) -> list[tuple[int, int]]:
    offsets = range(-2, 3)
    result: list[tuple[int, int]] = []
    for offset in offsets:
        total_months = year * 12 + (month - 1) + offset
        result.append((total_months // 12, total_months % 12 + 1))
    return result


def _validate_cutoff_day(cutoff_day: int) -> None:
    if not 1 <= cutoff_day <= 31:
        raise ValueError("payday cutoff days must be between 1 and 31")


def _validate_schedule(first_day: int, second_day: int) -> None:
    _validate_cutoff_day(first_day)
    _validate_cutoff_day(second_day)
    if first_day >= second_day:
        raise ValueError("payday cutoff days must be distinct and ascending")
