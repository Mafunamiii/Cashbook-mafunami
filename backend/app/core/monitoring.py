import sentry_sdk

from app.core.config import Settings


def initialize_sentry(settings: Settings) -> None:
    """Enable production monitoring when a Sentry DSN is configured."""
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        # Cashbook requests can contain credentials and financial details.
        max_request_body_size="never",
    )
