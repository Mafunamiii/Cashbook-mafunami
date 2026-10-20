from contextlib import nullcontext
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import ExchangeRateCache
from app.services.exchange_rates import (
    FRANKFURTER_V2_SOURCE,
    ExchangeRateNotFoundError,
    ExchangeRateProviderError,
    ExchangeRateService,
    FrankfurterV2Client,
)

REQUESTED_DATE = date(2026, 8, 9)


def _provider_with(handler) -> FrankfurterV2Client:
    return FrankfurterV2Client(
        "https://fx.example/v2", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _rate_response(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v2/rates"
    assert dict(request.url.params) == {"base": "AED", "quotes": "PHP", "date": "2026-08-09"}
    return httpx.Response(
        200,
        json=[{"date": "2026-08-07", "base": "AED", "quote": "PHP", "rate": 16.566}],
    )


def test_active_currency_catalog_uses_active_only_endpoint_and_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/v2/currencies"
        assert not request.url.params
        return httpx.Response(200, json=[{"iso_code": "JPY"}, {"iso_code": "PHP"}])

    monkeypatch.setattr(FrankfurterV2Client, "_active_currency_codes", None)
    monkeypatch.setattr(FrankfurterV2Client, "_active_currency_codes_expires_at", 0.0)
    provider = _provider_with(handler)
    assert provider.get_active_currency_codes() == frozenset({"JPY", "PHP"})
    assert provider.get_active_currency_codes() == frozenset({"JPY", "PHP"})
    assert calls == 1


def test_new_currency_selection_requires_the_active_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(FrankfurterV2Client, "_active_currency_codes", None)
    monkeypatch.setattr(FrankfurterV2Client, "_active_currency_codes_expires_at", 0.0)
    provider = _provider_with(
        lambda request: httpx.Response(200, json=[{"iso_code": "JPY"}, {"iso_code": "PHP"}])
    )
    service = ExchangeRateService(FakeSession(), provider)

    assert service.is_available_for_new_selection("JPY") is True
    assert service.is_available_for_new_selection("USD") is False


def test_catalog_outage_does_not_admit_a_new_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(FrankfurterV2Client, "_active_currency_codes", None)
    monkeypatch.setattr(FrankfurterV2Client, "_active_currency_codes_expires_at", 0.0)
    service = ExchangeRateService(
        FakeSession(), _provider_with(lambda request: httpx.Response(503))
    )

    with pytest.raises(ExchangeRateProviderError, match="catalog is unavailable"):
        service.is_available_for_new_selection("USD")


class FakeSession:
    def __init__(self, cached=None, fail_insert=False) -> None:
        self.cached = cached
        self.fail_insert = fail_insert
        self.added = []
        self.scalar_calls = 0

    def scalar(self, statement):
        self.scalar_calls += 1
        return self.cached

    def begin_nested(self):
        return nullcontext()

    def add(self, row) -> None:
        self.added.append(row)

    def flush(self) -> None:
        if self.fail_insert:
            self.cached = self.added[-1]
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))
        self.cached = self.added[-1]


@pytest.mark.parametrize("currency", ("PHP", "AED"))
def test_identity_avoids_http_and_cache(currency: str) -> None:
    db = FakeSession()
    provider = _provider_with(lambda request: pytest.fail("HTTP must not be called"))
    result = ExchangeRateService(db, provider).get_exchange_rate(currency, currency, REQUESTED_DATE)
    assert result.rate == Decimal("1")
    assert result.effective_date == REQUESTED_DATE
    assert result.source == "identity"
    assert db.scalar_calls == 0


def test_cache_hit_avoids_http_and_returns_persisted_snapshot() -> None:
    cached = ExchangeRateCache(
        source_currency_code="AED",
        target_currency_code="PHP",
        requested_date=REQUESTED_DATE,
        effective_date=date(2026, 8, 7),
        rate=Decimal("16.566"),
        source=FRANKFURTER_V2_SOURCE,
    )
    db = FakeSession(cached)
    provider = _provider_with(lambda request: pytest.fail("HTTP must not be called"))
    result = ExchangeRateService(db, provider).get_exchange_rate("aed", "php", REQUESTED_DATE)
    assert result.rate == Decimal("16.566")
    assert result.effective_date == date(2026, 8, 7)
    assert result.source == FRANKFURTER_V2_SOURCE


def test_cache_miss_fetches_and_persists_historical_effective_date() -> None:
    db = FakeSession()
    result = ExchangeRateService(db, _provider_with(_rate_response)).get_exchange_rate(
        "AED", "PHP", REQUESTED_DATE
    )
    assert result.rate == Decimal("16.566")
    assert result.effective_date == date(2026, 8, 7)
    assert len(db.added) == 1
    assert db.added[0].requested_date == REQUESTED_DATE
    assert db.added[0].source == FRANKFURTER_V2_SOURCE


def test_duplicate_cache_insert_returns_concurrently_persisted_record() -> None:
    db = FakeSession(fail_insert=True)
    result = ExchangeRateService(db, _provider_with(_rate_response)).get_exchange_rate(
        "AED", "PHP", REQUESTED_DATE
    )
    assert result.rate == Decimal("16.566")
    assert db.scalar_calls == 2


@pytest.mark.parametrize(
    ("handler", "error", "message"),
    [
        (lambda request: httpx.Response(503), ExchangeRateProviderError, "HTTP 503"),
        (
            lambda request: httpx.Response(200, content=b"not-json"),
            ExchangeRateProviderError,
            "malformed JSON",
        ),
        (lambda request: httpx.Response(200, json=[]), ExchangeRateNotFoundError, "no rate"),
        (
            lambda request: httpx.Response(
                200, json=[{"date": "2026-08-09", "base": "AED", "quote": "USD", "rate": 1}]
            ),
            ExchangeRateNotFoundError,
            "no matching rate",
        ),
    ],
)
def test_provider_errors_are_clear(handler, error: type[Exception], message: str) -> None:
    with pytest.raises(error, match=message):
        _provider_with(handler).get_rate("AED", "PHP", REQUESTED_DATE)


def test_provider_timeout_is_clear() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ExchangeRateProviderError, match="timed out"):
        _provider_with(timeout).get_rate("AED", "PHP", REQUESTED_DATE)


def test_provider_rejects_rate_after_requested_date() -> None:
    provider = _provider_with(
        lambda request: httpx.Response(
            200, json=[{"date": "2026-08-10", "base": "AED", "quote": "PHP", "rate": 16.5}]
        )
    )
    with pytest.raises(ExchangeRateProviderError, match="later"):
        provider.get_rate("AED", "PHP", REQUESTED_DATE)


def test_unknown_currency_is_rejected_before_http() -> None:
    with pytest.raises(ValueError, match="Unsupported currency"):
        ExchangeRateService(FakeSession(), _provider_with(_rate_response)).get_exchange_rate(
            "ZZZ", "PHP", REQUESTED_DATE
        )
