"""Database engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


database_url = get_settings().database_url
# SQLite disallows using a connection across threads by default. FastAPI's
# sync (def, not async def) route handlers run in a thread pool, so without
# this, concurrent requests against a local sqlite:// DATABASE_URL (the
# common no-Postgres-installed local dev setup) would intermittently fail
# with "SQLite objects created in a thread can only be used in that same
# thread." Postgres has no such restriction, so this only applies to sqlite.
_connect_args: dict = {}
if database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

_engine = create_engine(database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables that do not already exist.

    This is a deliberate v1 simplification: schema changes are applied by
    editing the models and re-running this, not through migrations. Add
    Alembic before making breaking schema changes against a database that
    already holds real customer data.
    """

    from app import models  # noqa: F401 -- ensures models are registered on Base

    Base.metadata.create_all(bind=_engine)


def get_db() -> Iterator[Session]:
    """Yield a database session for one request, closing it afterward.

    Yields:
        Active SQLAlchemy session.
    """

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
