from types import SimpleNamespace

import httpx
import pytest

from app.api.currencies import list_currencies
from app.services.exchange_rates import FrankfurterV2Client


def _settings() -> SimpleNamespace:
    return SimpleNamespace(frankfurter_base_url="https://fx.example/v2")


@pytest.fixture(autouse=True)
def isolate_currency_catalog_cache(monkeypatch):
    monkeypatch.setattr(FrankfurterV2Client, "_active_currency_codes", None)
    monkeypatch.setattr(FrankfurterV2Client, "_active_currency_codes_expires_at", 0.0)


def test_currency_catalog_uses_frankfurter_when_available(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/currencies"
        return httpx.Response(200, json=[{"iso_code": "JPY"}, {"iso_code": "PHP"}])

    monkeypatch.setattr(
        "app.api.currencies.FrankfurterV2Client",
        lambda base_url: FrankfurterV2Client(
            base_url, client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )

    result = list_currencies(None, None, _settings())

    assert [currency.code for currency in result] == ["JPY", "PHP"]


def test_currency_catalog_falls_back_locally_when_frankfurter_is_unavailable(monkeypatch) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ConnectError("DNS failure", request=request)

    monkeypatch.setattr(
        "app.api.currencies.FrankfurterV2Client",
        lambda base_url: FrankfurterV2Client(
            base_url, client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )

    result = list_currencies(None, None, _settings())
    currencies = {currency.code: currency for currency in result}

    assert len(requests) == 1
    assert "PHP" in currencies
    assert "AED" in currencies
    assert currencies["PHP"].name
    assert currencies["AED"].name
