from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def create_database_engine() -> Engine:
    database_url = get_settings().database_url
    if database_url is None:
        raise RuntimeError("DATABASE_URL must be configured before using PostgreSQL")
    return create_engine(str(database_url), pool_pre_ping=True)


def create_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=create_database_engine(), autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """Provide a short-lived database session for one API request."""
    session = create_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database_connection() -> None:
    """Raise if PostgreSQL cannot accept a simple query."""
    with create_database_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
