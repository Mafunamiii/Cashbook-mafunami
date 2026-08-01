"""PostgreSQL-backed fixtures for API integration tests.

Set TEST_DATABASE_URL to run these tests. They refuse to infer a database
target, preventing accidental execution against a developer database.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.rate_limit import login_rate_limiter
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app


@pytest.fixture(scope="session")
def integration_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    database_name = make_url(url).database or ""
    if not database_name.lower().endswith("_test"):
        pytest.fail(
            "TEST_DATABASE_URL must target a database whose name ends in '_test'; "
            f"refusing destructive test setup for {database_name!r}"
        )
    return url


@pytest.fixture(scope="session")
def engine(integration_url: str) -> Generator[Engine, None, None]:
    engine = create_engine(integration_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def reset_database(engine: Engine) -> Generator[None, None, None]:
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
    login_rate_limiter._attempts.clear()  # test isolation for process-local limiter
    yield


@pytest.fixture
def db_session(engine: Engine) -> Generator[Session, None, None]:
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, reset_database: None
) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    monkeypatch.setenv("INITIAL_INVITE_CODE", "integration-invite-code")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_ATTEMPTS", "2")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
