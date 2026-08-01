from datetime import date

import pytest

from app.domain.periods import (
    ReportingPeriod,
    calendar_month_period,
    effective_payday,
    payday_period,
    payday_periods_starting_in_month,
    transaction_period,
    versioned_payday_period,
)


@pytest.mark.parametrize(
    ("value", "expected_start", "expected_end"),
    [
        (date(2026, 8, 1), date(2026, 8, 1), date(2026, 8, 31)),
        (date(2024, 2, 15), date(2024, 2, 1), date(2024, 2, 29)),
        (date(2023, 2, 15), date(2023, 2, 1), date(2023, 2, 28)),
    ],
)
def test_calendar_month_period(value: date, expected_start: date, expected_end: date) -> None:
    assert calendar_month_period(value).start == expected_start
    assert calendar_month_period(value).end == expected_end


@pytest.mark.parametrize(
    ("year", "month", "cutoff", "expected"),
    [
        (2024, 2, 30, date(2024, 2, 29)),
        (2023, 2, 31, date(2023, 2, 28)),
        (2026, 4, 31, date(2026, 4, 30)),
        (2026, 1, 31, date(2026, 1, 31)),
    ],
)
def test_effective_payday_clamps_to_month_end(
    year: int, month: int, cutoff: int, expected: date
) -> None:
    assert effective_payday(year, month, cutoff) == expected


@pytest.mark.parametrize(
    ("value", "expected_start", "expected_end"),
    [
        (date(2026, 8, 11), date(2026, 7, 27), date(2026, 8, 11)),
        (date(2026, 8, 12), date(2026, 8, 12), date(2026, 8, 26)),
        (date(2026, 8, 26), date(2026, 8, 12), date(2026, 8, 26)),
        (date(2026, 8, 27), date(2026, 8, 27), date(2026, 9, 11)),
        (date(2027, 1, 1), date(2026, 12, 27), date(2027, 1, 11)),
    ],
)
def test_payday_periods_for_standard_two_payday_schedule(
    value: date, expected_start: date, expected_end: date
) -> None:
    assert payday_period(value, 12, 27).start == expected_start
    assert payday_period(value, 12, 27).end == expected_end


@pytest.mark.parametrize(
    ("value", "expected_start", "expected_end"),
    [
        (date(2024, 2, 28), date(2024, 1, 31), date(2024, 2, 28)),
        (date(2024, 2, 29), date(2024, 2, 29), date(2024, 3, 29)),
        (date(2023, 2, 28), date(2023, 2, 28), date(2023, 3, 29)),
        (date(2026, 4, 30), date(2026, 4, 30), date(2026, 5, 29)),
    ],
)
def test_payday_period_handles_clamped_cutoffs_and_leap_years(
    value: date, expected_start: date, expected_end: date
) -> None:
    assert payday_period(value, 30, 31).start == expected_start
    assert payday_period(value, 30, 31).end == expected_end


def test_transaction_date_is_assigned_to_its_payday_period() -> None:
    assert transaction_period(date(2026, 1, 1), 12, 27) == payday_period(date(2026, 1, 1), 12, 27)


def test_payday_periods_starting_in_month_deduplicates_clamped_boundaries() -> None:
    periods = payday_periods_starting_in_month(date(2024, 2, 1), 30, 31)
    assert periods == [payday_period(date(2024, 2, 29), 30, 31)]


def test_payday_periods_starting_in_month_requires_calendar_month_start() -> None:
    with pytest.raises(ValueError, match="first"):
        payday_periods_starting_in_month(date(2026, 8, 2), 12, 27)


def test_versioned_payday_period_truncates_before_a_later_schedule_change() -> None:
    schedules = [
        (date(2026, 8, 12), 12, 27),
        (date(2026, 9, 15), 15, 28),
    ]
    assert versioned_payday_period(date(2026, 9, 13), schedules) == ReportingPeriod(
        date(2026, 9, 12), date(2026, 9, 14)
    )
    assert versioned_payday_period(date(2026, 9, 15), schedules) == ReportingPeriod(
        date(2026, 9, 15), date(2026, 9, 27)
    )


@pytest.mark.parametrize("first_day, second_day", [(0, 12), (12, 32), (12, 12), (27, 12)])
def test_invalid_payday_schedules_are_rejected(first_day: int, second_day: int) -> None:
    with pytest.raises(ValueError):
        payday_period(date(2026, 1, 1), first_day, second_day)
