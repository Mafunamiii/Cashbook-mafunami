from unittest.mock import Mock

from app.core.config import Settings
from app.core.monitoring import initialize_sentry


def test_sentry_is_disabled_without_a_dsn(monkeypatch) -> None:
    init = Mock()
    monkeypatch.setattr("app.core.monitoring.sentry_sdk.init", init)

    initialize_sentry(Settings())

    init.assert_not_called()


def test_sentry_uses_privacy_safe_defaults(monkeypatch) -> None:
    init = Mock()
    monkeypatch.setattr("app.core.monitoring.sentry_sdk.init", init)

    initialize_sentry(
        Settings(
            sentry_dsn="https://public@example.ingest.sentry.io/1",
            sentry_release="cashbook@test-release",
            sentry_traces_sample_rate=0.1,
        )
    )

    init.assert_called_once_with(
        dsn="https://public@example.ingest.sentry.io/1",
        environment="development",
        release="cashbook@test-release",
        traces_sample_rate=0.1,
        send_default_pii=False,
        max_request_body_size="never",
    )


def test_sentry_treats_an_empty_release_as_unset(monkeypatch) -> None:
    init = Mock()
    monkeypatch.setattr("app.core.monitoring.sentry_sdk.init", init)

    initialize_sentry(
        Settings(sentry_dsn="https://public@example.ingest.sentry.io/1", sentry_release="")
    )

    assert init.call_args.kwargs["release"] is None
