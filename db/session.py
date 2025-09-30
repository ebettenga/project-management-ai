"""Engine and session helpers."""

from __future__ import annotations

import contextlib
from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings


def _build_conn_str() -> str:
    conn_str = get_settings().postgres_url
    if not conn_str:
        raise RuntimeError("POSTGRES_URL is not configured")
    return conn_str


_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def get_engine(echo: bool = False) -> Engine:
    """Return a singleton SQLAlchemy engine."""

    global _engine, SessionLocal  # pylint: disable=global-statement
    if _engine is None:
        conn_str = _build_conn_str()
        _engine = create_engine(conn_str, echo=echo)
        SessionLocal = sessionmaker(
            bind=_engine,
            autoflush=False,
            expire_on_commit=False,
        )
    return _engine


@contextlib.contextmanager
def get_session(*, echo: bool = False) -> Generator[Session, None, None]:
    """Context manager yielding a session tied to the configured engine."""

    engine = get_engine(echo=echo)
    assert SessionLocal is not None  # for type checkers
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
