"""Small, explicit currency rules for transaction conversion metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from iso4217 import Currency

IDENTITY_EXCHANGE_RATE = Decimal("1")
IDENTITY_EXCHANGE_RATE_SOURCE = "identity"
MAX_SIGNED_BIGINT = 9_223_372_036_854_775_807
LOCAL_CURRENCY_CODES = frozenset(currency.value for currency in Currency)


def normalize_currency_code(value: str) -> str:
    """Return a locally-known ISO 4217 code or raise ValueError.

    Availability for *new* selections is deliberately a provider-catalog
    concern.  This local check keeps persisted values parseable offline.
    """
    if not isinstance(value, str):
        raise ValueError("Unsupported currency code.")
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("Unsupported currency code.")
    try:
        Currency(normalized)
    except (KeyError, ValueError):
        raise ValueError("Unsupported currency code.") from None
    return normalized


def currency_metadata(currency_code: str) -> tuple[str, int]:
    currency = Currency(normalize_currency_code(currency_code))
    # ISO 4217 represents currencies without a decimal subdivision as 0.
    if currency.exponent is None:
        raise ValueError("Currency has no minor unit metadata.")
    return currency.currency_name, int(currency.exponent)


def local_currency_codes() -> frozenset[str]:
    """Return the locally available currency catalog for offline use."""
    return LOCAL_CURRENCY_CODES


def currency_minor_unit_exponent(currency_code: str) -> int:
    return currency_metadata(currency_code)[1]


@dataclass(frozen=True)
class IdentityConversion:
    base_amount_minor: int
    base_currency_code: str
    exchange_rate: Decimal
    exchange_rate_date: date
    exchange_rate_source: str


def identity_conversion(
    amount_minor: int, currency_code: str, rate_date: date
) -> IdentityConversion:
    """Create immutable metadata for an amount already in its base currency."""
    normalized_currency = normalize_currency_code(currency_code)
    return IdentityConversion(
        base_amount_minor=amount_minor,
        base_currency_code=normalized_currency,
        exchange_rate=IDENTITY_EXCHANGE_RATE,
        exchange_rate_date=rate_date,
        exchange_rate_source=IDENTITY_EXCHANGE_RATE_SOURCE,
    )


def convert_amount_minor(
    amount_minor: int,
    source_currency_code: str,
    target_currency_code: str,
    exchange_rate: Decimal,
) -> int:
    """Convert minor units using ``base_amount = original_amount * exchange_rate``.

    The result is rounded to target minor units with ROUND_HALF_EVEN (banker's
    rounding), a deterministic financial policy that avoids systematic upward
    bias across many conversions.
    """
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor < 0:
        raise ValueError("amount_minor must be a non-negative integer.")
    if (
        not isinstance(exchange_rate, Decimal)
        or not exchange_rate.is_finite()
        or exchange_rate <= 0
    ):
        raise ValueError("exchange_rate must be a positive finite Decimal.")

    source_exponent = currency_minor_unit_exponent(source_currency_code)
    target_exponent = currency_minor_unit_exponent(target_currency_code)
    source_amount = Decimal(amount_minor).scaleb(-source_exponent)
    target_minor = (source_amount * exchange_rate).scaleb(target_exponent)
    converted = int(target_minor.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
    if converted > MAX_SIGNED_BIGINT:
        raise ValueError("Converted amount exceeds the supported range.")
    return converted
