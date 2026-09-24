from types import SimpleNamespace

import httpx

from app.api.currencies import list_currencies
from app.services.exchange_rates import FrankfurterV2Client


def _settings() -> SimpleNamespace:
    return SimpleNamespace(frankfurter_base_url="https://fx.example/v2")


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
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS failure", request=request)

    monkeypatch.setattr(
        "app.api.currencies.FrankfurterV2Client",
        lambda base_url: FrankfurterV2Client(
            base_url, client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )

    result = list_currencies(None, None, _settings())
    currencies = {currency.code: currency for currency in result}

    assert "PHP" in currencies
    assert "AED" in currencies
    assert currencies["PHP"].name
    assert currencies["AED"].name
