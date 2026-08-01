from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded exclusively from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn | None = None
    environment: Literal["development", "production"] = "development"
    registration_mode: Literal["invite_only", "open"] = "invite_only"
    initial_invite_code: SecretStr | None = None
    session_cookie_name: str = "cashbook_session"
    csrf_cookie_name: str = "cashbook_csrf"
    frontend_origin: str = "http://localhost:5173"
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict"] = "lax"
    session_ttl_hours: int = Field(default=168, ge=1, le=24 * 365)
    login_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    login_rate_limit_window_seconds: int = Field(default=300, ge=1, le=86_400)
    sentry_dsn: str | None = None
    sentry_release: str | None = None
    sentry_traces_sample_rate: float = Field(default=0.05, ge=0, le=1)
    # `testserver` is FastAPI's in-process test-client host. Production must
    # override this value with its explicit public host names.
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    forwarded_allow_ips: str = "127.0.0.1"
    manual_recovery_message: str = (
        "Contact your Cashbook administrator to reset your password. "
        "Password recovery is performed manually."
    )

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Reject accidental production startup with development-safe defaults."""
        if self.environment != "production":
            return self

        errors: list[str] = []
        if self.database_url is None:
            errors.append("DATABASE_URL must be set in production")
        if not self.frontend_origin.startswith("https://"):
            errors.append("FRONTEND_ORIGIN must use https in production")
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true in production")
        if self.registration_mode == "invite_only":
            invite_code = (
                self.initial_invite_code.get_secret_value() if self.initial_invite_code else ""
            )
            if len(invite_code) < 20 or "replace-with" in invite_code.lower():
                errors.append(
                    "INITIAL_INVITE_CODE must be a non-placeholder secret of at least 20 characters"
                )
        if not self.trusted_host_list or "*" in self.trusted_host_list:
            errors.append("TRUSTED_HOSTS must name explicit hosts in production")
        if not self.forwarded_allow_ips.strip():
            errors.append("FORWARDED_ALLOW_IPS must be set in production")
        if errors:
            raise ValueError("; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
