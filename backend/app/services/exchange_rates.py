"""Deterministic historical FX lookup with a shared persistent cache."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import ExchangeRateCache
from app.domain.currency import IDENTITY_EXCHANGE_RATE, normalize_currency_code

FRANKFURTER_V2_SOURCE = "frankfurter-v2"
FRANKFURTER_TIMEOUT_SECONDS = 10.0
FRANKFURTER_CATALOG_TTL_SECONDS = 60 * 60


class ExchangeRateError(RuntimeError):
    """A requested historical FX observation could not be resolved."""


class ExchangeRateProviderError(ExchangeRateError):
    """Frankfurter could not return a valid rate response."""


class ExchangeRateNotFoundError(ExchangeRateError):
    """The provider had no usable historical observation for the request."""


@dataclass(frozen=True)
class ExchangeRateResult:
    rate: Decimal
    requested_date: date
    effective_date: date
    source: str


class FrankfurterV2Client:
    """Small synchronous client for Frankfurter's v2 targeted rate endpoint."""

    def __init__(self, base_url: str, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=FRANKFURTER_TIMEOUT_SECONDS)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    _active_currency_codes: frozenset[str] | None = None
    _active_currency_codes_expires_at = 0.0

    def get_active_currency_codes(self) -> frozenset[str]:
        """Fetch Frankfurter's active-only currency reference catalog.

        The v2 endpoint without ``scope=all`` intentionally excludes legacy
        currencies.  The process cache avoids coupling every form submission
        to this reference-data request.
        """
        now = time.monotonic()
        cls = type(self)
        if cls._active_currency_codes is not None and now < cls._active_currency_codes_expires_at:
            return cls._active_currency_codes
        try:
            response = self._client.get(
                f"{self._base_url}/currencies", timeout=FRANKFURTER_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            payload: Any = json.loads(response.content)
        except (httpx.HTTPError, UnicodeDecodeError, ValueError, TypeError) as exc:
            raise ExchangeRateProviderError("Frankfurter currency catalog is unavailable.") from exc
        if not isinstance(payload, list):
            raise ExchangeRateProviderError("Frankfurter returned a malformed currency catalog.")
        codes = frozenset(
            row.get("iso_code", row.get("code"))
            for row in payload
            if isinstance(row, dict)
            and isinstance(row.get("iso_code", row.get("code")), str)
            and len(row.get("iso_code", row.get("code"))) == 3
            and row.get("iso_code", row.get("code")).isupper()
        )
        if not codes:
            raise ExchangeRateProviderError("Frankfurter returned an empty currency catalog.")
        cls._active_currency_codes = codes
        cls._active_currency_codes_expires_at = now + FRANKFURTER_CATALOG_TTL_SECONDS
        return codes

    def get_rate(
        self, source_currency: str, target_currency: str, requested_date: date
    ) -> ExchangeRateResult:
        try:
            response = self._client.get(
                f"{self._base_url}/rates",
                params={
                    "base": source_currency,
                    "quotes": target_currency,
                    "date": requested_date.isoformat(),
                },
                timeout=FRANKFURTER_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ExchangeRateProviderError("Frankfurter request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise ExchangeRateProviderError(
                f"Frankfurter returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise ExchangeRateProviderError("Frankfurter request failed.") from exc

        try:
            payload: Any = json.loads(response.content, parse_float=Decimal, parse_int=Decimal)
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            raise ExchangeRateProviderError("Frankfurter returned malformed JSON.") from exc
        if not isinstance(payload, list) or not payload:
            raise ExchangeRateNotFoundError("Frankfurter returned no rate for the requested date.")

        matching_rows = [
            row
            for row in payload
            if isinstance(row, dict)
            and row.get("base") == source_currency
            and row.get("quote") == target_currency
        ]
        if len(matching_rows) != 1:
            raise ExchangeRateNotFoundError(
                "Frankfurter returned no matching rate for the requested pair."
            )
        row = matching_rows[0]
        try:
            effective_date = date.fromisoformat(row["date"])
            rate = Decimal(row["rate"])
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ExchangeRateProviderError(
                "Frankfurter returned a malformed rate record."
            ) from exc
        if not rate.is_finite() or rate <= 0:
            raise ExchangeRateProviderError("Frankfurter returned an invalid exchange rate.")
        if effective_date > requested_date:
            raise ExchangeRateProviderError(
                "Frankfurter returned a rate later than the requested date."
            )
        return ExchangeRateResult(rate, requested_date, effective_date, FRANKFURTER_V2_SOURCE)


class ExchangeRateService:
    def __init__(self, db: Session, provider: FrankfurterV2Client) -> None:
        self._db = db
        self._provider = provider

    def get_exchange_rate(
        self, source_currency: str, target_currency: str, transaction_date: date
    ) -> ExchangeRateResult:
        source = normalize_currency_code(source_currency)
        target = normalize_currency_code(target_currency)
        if source == target:
            return ExchangeRateResult(
                IDENTITY_EXCHANGE_RATE, transaction_date, transaction_date, "identity"
            )

        cached = self._find_cached(source, target, transaction_date)
        if cached is not None:
            return self._result_from_cache(cached)

        resolved = self._provider.get_rate(source, target, transaction_date)
        cached = ExchangeRateCache(
            source_currency_code=source,
            target_currency_code=target,
            requested_date=transaction_date,
            effective_date=resolved.effective_date,
            rate=resolved.rate,
            source=resolved.source,
        )
        try:
            # A savepoint preserves the caller's transaction if another worker
            # inserts the same logical cache record first.
            with self._db.begin_nested():
                self._db.add(cached)
                self._db.flush()
        except IntegrityError:
            cached = self._find_cached(source, target, transaction_date)
            if cached is None:
                raise
        return self._result_from_cache(cached)

    def is_available_for_new_selection(self, currency_code: str) -> bool:
        """Check a new selection against Frankfurter's active catalog."""
        code = normalize_currency_code(currency_code)
        return code in self._provider.get_active_currency_codes()

    def _find_cached(
        self, source: str, target: str, requested_date: date
    ) -> ExchangeRateCache | None:
        return self._db.scalar(
            select(ExchangeRateCache).where(
                ExchangeRateCache.source == FRANKFURTER_V2_SOURCE,
                ExchangeRateCache.source_currency_code == source,
                ExchangeRateCache.target_currency_code == target,
                ExchangeRateCache.requested_date == requested_date,
            )
        )

    @staticmethod
    def _result_from_cache(cached: ExchangeRateCache) -> ExchangeRateResult:
        return ExchangeRateResult(
            rate=Decimal(cached.rate),
            requested_date=cached.requested_date,
            effective_date=cached.effective_date,
            source=cached.source,
        )


def create_exchange_rate_service(db: Session, settings: Settings) -> ExchangeRateService:
    """Construct the service for future transaction snapshot use."""
    return ExchangeRateService(db, FrankfurterV2Client(settings.frankfurter_base_url))
