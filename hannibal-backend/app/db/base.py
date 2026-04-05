from __future__ import annotations

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
