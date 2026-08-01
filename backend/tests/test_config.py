import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_settings_reject_insecure_cookie() -> None:
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(
            database_url="postgresql+psycopg://cashbook:password@db:5432/cashbook",
            environment="production",
            frontend_origin="https://cashbook.example.test",
            cookie_secure=False,
            initial_invite_code="a" * 24,
            trusted_hosts="cashbook.example.test",
            forwarded_allow_ips="*",
        )


def test_production_settings_accept_explicit_secure_configuration() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://cashbook:password@db:5432/cashbook",
        environment="production",
        frontend_origin="https://cashbook.example.test",
        cookie_secure=True,
        initial_invite_code="a" * 24,
        trusted_hosts="cashbook.example.test",
        forwarded_allow_ips="172.17.0.1",
    )

    assert settings.trusted_host_list == ["cashbook.example.test"]


def test_display_name_rejects_whitespace_only_value() -> None:
    from app.api.schemas import SettingsUpdateRequest

    with pytest.raises(ValidationError, match="Display name cannot be blank"):
        SettingsUpdateRequest(display_name="   ")
