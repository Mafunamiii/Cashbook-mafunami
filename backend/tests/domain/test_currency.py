from datetime import date
from decimal import Decimal

import pytest

from app.domain.currency import (
    IDENTITY_EXCHANGE_RATE,
    convert_amount_minor,
    currency_minor_unit_exponent,
    identity_conversion,
    normalize_currency_code,
)


def test_known_currency_codes_are_normalized_and_have_minor_units() -> None:
    assert normalize_currency_code(" php ") == "PHP"
    assert normalize_currency_code("aed") == "AED"
    assert currency_minor_unit_exponent("PHP") == 2
    assert currency_minor_unit_exponent("AED") == 2
    assert currency_minor_unit_exponent("JPY") == 0
    assert currency_minor_unit_exponent("BHD") == 3


def test_currency_without_minor_unit_metadata_is_rejected() -> None:
    with pytest.raises(ValueError, match="minor unit metadata"):
        currency_minor_unit_exponent("XAU")


@pytest.mark.parametrize("value", ["", "PH", "PHPH", "1ED", None])
def test_unsupported_currency_codes_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        normalize_currency_code(value)  # type: ignore[arg-type]


def test_convert_amount_minor_uses_forward_rate_direction_and_decimal_math() -> None:
    # base_amount = original_amount * exchange_rate: 1 AED = 16.566 PHP.
    assert convert_amount_minor(100, "AED", "PHP", Decimal("16.566")) == 1_657
    assert convert_amount_minor(1_656, "PHP", "AED", Decimal("0.0603646")) == 100


def test_convert_amount_minor_uses_half_even_rounding() -> None:
    assert convert_amount_minor(1, "PHP", "AED", Decimal("0.005")) == 0
    assert convert_amount_minor(3, "PHP", "AED", Decimal("0.005")) == 2


def test_convert_amount_minor_rejects_float_rates() -> None:
    with pytest.raises(ValueError, match="Decimal"):
        convert_amount_minor(100, "PHP", "AED", 1.5)  # type: ignore[arg-type]


def test_convert_amount_minor_uses_currency_minor_unit_metadata() -> None:
    assert convert_amount_minor(1_000, "JPY", "PHP", Decimal("0.40")) == 40_000
    assert convert_amount_minor(1_250, "BHD", "PHP", Decimal("150")) == 18_750


def test_identity_conversion_preserves_integer_amount_and_decimal_rate() -> None:
    conversion = identity_conversion(9_223_372_036_854_775_807, "PHP", date(2026, 8, 1))

    assert conversion.base_amount_minor == 9_223_372_036_854_775_807
    assert conversion.base_currency_code == "PHP"
    assert conversion.exchange_rate == Decimal("1")
    assert isinstance(conversion.exchange_rate, Decimal)
    assert conversion.exchange_rate == IDENTITY_EXCHANGE_RATE
    assert conversion.exchange_rate_date == date(2026, 8, 1)
    assert conversion.exchange_rate_source == "identity"
