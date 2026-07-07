"""Main FastAPI application entry point for Hannibal backend."""

from __future__ import annotations

import contextlib
from typing import AsyncGenerator

import redis.asyncio as redis
import sentry_sdk
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.core.dependencies import close_redis as close_shared_redis
from app.db.base import get_async_session_maker
from app.middleware.rate_limiter import limiter, setup_rate_limiter
from app.core.exceptions import (
    NotFoundError,
    ForbiddenError,
    ConflictError,
    UnauthorizedError,
    SlotNotAvailableError,
    WhatsAppError,
    GoogleCalendarError,
    AIServiceError,
)
from app.db.base import get_engine
from app.utils.logger import configure_logging, get_logger

# Import routers
from app.modules.whatsapp.router import router as whatsapp_router
from app.modules.scheduling.router import router as scheduling_router
from app.modules.offices.router import router as offices_router
from app.modules.patients.router import router as patients_router
from app.modules.google_calendar.router import router as google_calendar_router

logger = get_logger(__name__)


# Global Redis connection
redis_client: redis.Redis | None = None


async def init_redis() -> None:
    """Initialize Redis connection."""
    global redis_client
    try:
        redis_client = await redis.from_url(
            settings.redis_url,
            encoding="utf8",
            decode_responses=True,
        )
        await redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error("Redis connection failed", error=str(e))
        raise


async def close_redis() -> None:
    """Close Redis connection."""
    global redis_client
    if redis_client:
        await redis_client.close()
        logger.info("Redis connection closed")


def init_sentry() -> None:
    """Initialize Sentry error tracking."""
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.1,
            integrations=[],
        )
        logger.info("Sentry initialized")


async def close_db() -> None:
    """Close database engine."""
    engine = get_engine()
    if engine:
        await engine.dispose()
    logger.info("Database connections closed")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown."""
    # Startup
    logger.info("Starting Hannibal backend")
    configure_logging("INFO")
    init_sentry()
    await init_redis()

    yield

    # Shutdown
    logger.info("Shutting down Hannibal backend")
    await close_redis()
    await close_shared_redis()
    await close_db()


# Create FastAPI app
app = FastAPI(
    title="Hannibal Backend",
    description="AI-powered medical appointment scheduling system",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (default limits for all routes; webhook/health are exempt)
setup_rate_limiter(app)


# Health check endpoint
@app.get("/health")
@limiter.exempt
async def health_check() -> JSONResponse:
    """Health check endpoint.

    Verifies connectivity to the database and Redis. Returns 503 if either
    dependency is unreachable so the platform health check fails fast.
    """
    db_ok = False
    redis_ok = False

    # Check database
    try:
        async with get_async_session_maker()() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        logger.error("health_check_db_failed", error=str(e))

    # Check Redis
    try:
        if redis_client is None:
            raise RuntimeError("Redis client not initialized")
        await redis_client.ping()
        redis_ok = True
    except Exception as e:
        logger.error("health_check_redis_failed", error=str(e))

    healthy = db_ok and redis_ok
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "service": "hannibal-backend",
            "database": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
    )


# Error handlers for custom exceptions
@app.exception_handler(NotFoundError)
async def not_found_exception_handler(request, exc: NotFoundError):
    """Handle NotFoundError exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(ForbiddenError)
async def forbidden_exception_handler(request, exc: ForbiddenError):
    """Handle ForbiddenError exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(ConflictError)
async def conflict_exception_handler(request, exc: ConflictError):
    """Handle ConflictError exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(UnauthorizedError)
async def unauthorized_exception_handler(request, exc: UnauthorizedError):
    """Handle UnauthorizedError exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "headers": exc.headers},
    )


@app.exception_handler(SlotNotAvailableError)
async def slot_not_available_exception_handler(request, exc: SlotNotAvailableError):
    """Handle SlotNotAvailableError exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(WhatsAppError)
async def whatsapp_exception_handler(request, exc: WhatsAppError):
    """Handle WhatsAppError exceptions."""
    logger.error("WhatsApp error", detail=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(GoogleCalendarError)
async def google_calendar_exception_handler(request, exc: GoogleCalendarError):
    """Handle GoogleCalendarError exceptions."""
    logger.error("Google Calendar error", detail=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(AIServiceError)
async def ai_service_exception_handler(request, exc: AIServiceError):
    """Handle AIServiceError exceptions."""
    logger.error("AI service error", detail=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """Handle generic HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc: Exception):
    """Handle generic exceptions."""
    logger.error("Unhandled exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Include routers with prefixes
app.include_router(whatsapp_router, prefix="/api/whatsapp", tags=["whatsapp"])
app.include_router(scheduling_router, prefix="/api/scheduling", tags=["scheduling"])
app.include_router(offices_router, prefix="/api/offices", tags=["offices"])
app.include_router(patients_router, prefix="/api/patients", tags=["patients"])
app.include_router(
    google_calendar_router,
    prefix="/api/google-calendar",
    tags=["google-calendar"],
)
