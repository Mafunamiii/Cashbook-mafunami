"""Application-facing active currency reference data."""

from fastapi import APIRouter

from app.api.dependencies import ActiveUser, AppSettings, DatabaseSession
from app.api.schemas import CurrencyResponse
from app.domain.currency import currency_metadata, local_currency_codes
from app.services.exchange_rates import ExchangeRateProviderError, FrankfurterV2Client

router = APIRouter(prefix="/api/v1/currencies", tags=["currencies"])


@router.get("", response_model=list[CurrencyResponse])
def list_currencies(
    current_user: ActiveUser, db: DatabaseSession, settings: AppSettings
) -> list[CurrencyResponse]:
    # Authentication keeps reference data access consistent with the rest of
    # the SPA API.  db is intentionally unused but retains the normal endpoint
    # dependency pattern.
    del current_user, db
    client = FrankfurterV2Client(settings.frankfurter_base_url)
    try:
        codes = client.get_active_currency_codes()
    except ExchangeRateProviderError:
        codes = local_currency_codes()
    finally:
        client.close()
    result = []
    for code in codes:
        try:
            name, minor_unit = currency_metadata(code)
        except ValueError:
            continue
        if not 0 <= minor_unit <= 3:
            continue
        result.append(CurrencyResponse(code=code, name=name, minor_unit=minor_unit))
    return sorted(result, key=lambda item: item.code)
