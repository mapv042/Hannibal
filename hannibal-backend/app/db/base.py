from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass


# Engine and session factory — created lazily on first use
_engine = None
_async_session_maker = None


def get_engine():
    """Get or create the async engine (lazy initialization)."""
    global _engine
    if _engine is None:
        from app.config import settings
        _engine = create_async_engine(
            settings.async_database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=0,
            pool_recycle=300,  # recycle before Supabase's pooler drops idle connections
            connect_args={
                # Supabase Supavisor runs in transaction mode (port 6543), which does
                # not support cached/named prepared statements shared across server
                # connections. Disable caching and give each statement a unique name
                # so they can't collide on a reused pooled connection.
                "statement_cache_size": 0,
                "prepared_statement_cache_size": 0,
                "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
            },
        )
    return _engine


def get_async_session_maker():
    """Get or create the async session factory (lazy initialization)."""
    global _async_session_maker
    if _async_session_maker is None:
        _async_session_maker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _async_session_maker


async def dispose_engine() -> None:
    """Close every pooled connection and drop the cached engine.

    Celery runs each task body in its own `asyncio.run()`, which creates an event
    loop and closes it on the way out. The asyncpg connections the pool keeps are
    bound to the loop that opened them, so the *next* task in the same worker
    process checks out a connection whose loop is gone and fails — first as
    "attached to a different loop" on the pre-ping, then as
    "connection was closed in the middle of operation". Only the first task after
    a worker boots ever succeeded.

    Disposing inside the task's own loop closes those connections while their
    loop is still alive and forces the next task to build a fresh engine. Call it
    at the end of every task body (see app.core.task_runner.run_task); the API
    process must NOT call it per request, where one long-lived pool is correct.
    """
    global _engine, _async_session_maker

    if _engine is not None:
        await _engine.dispose()

    _engine = None
    _async_session_maker = None
