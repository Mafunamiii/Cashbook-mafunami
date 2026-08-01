"""Fail fast when the backend's environment is not safe for its selected mode."""

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    # Intentionally print only non-sensitive operational values.
    print(
        "Cashbook environment validation passed "
        f"(environment={settings.environment}, registration_mode={settings.registration_mode})."
    )


if __name__ == "__main__":
    main()
