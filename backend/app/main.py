from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.budgets import router as budgets_router
from app.api.categories import router as categories_router
from app.api.currencies import router as currencies_router
from app.api.settings import router as settings_router
from app.api.transactions import router as transactions_router
from app.core.config import get_settings
from app.core.monitoring import initialize_sentry
from app.db.session import check_database_connection

settings = get_settings()
initialize_sentry(settings)
app = FastAPI(title="Cashbook API", version="0.1.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    # The budget configuration endpoints use PUT.  Keep this explicit rather
    # than falling back to an overly broad CORS policy.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "sentry-trace", "baggage"],
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(settings_router)
app.include_router(categories_router)
app.include_router(currencies_router)
app.include_router(transactions_router)
app.include_router(budgets_router)


@app.get("/health", tags=["operations"])
def health_check() -> dict[str, str]:
    """Liveness endpoint: the API process is accepting requests."""
    return {"status": "ok"}


@app.get("/ready", tags=["operations"])
def readiness_check() -> dict[str, str]:
    """Readiness endpoint: PostgreSQL must be reachable."""
    try:
        check_database_connection()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ok"}
