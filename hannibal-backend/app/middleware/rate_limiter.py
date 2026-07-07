"""Rate limiting middleware using slowapi."""

from __future__ import annotations

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from fastapi import FastAPI

# Rate limit definitions for different endpoint types
API_LIMIT = "60/minute"  # Standard API endpoints (default)
AUTH_LIMIT = "5/minute"  # Authentication endpoints

# Module-level limiter so routers can decorate endpoints (`@limiter.exempt`,
# `@limiter.limit(...)`) without importing the app. The Meta webhook and the
# health check are exempted where they are defined — webhook traffic volume is
# Meta's, not a client's.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[API_LIMIT],
)


def setup_rate_limiter(app: FastAPI) -> Limiter:
    """
    Setup rate limiting for the FastAPI application.

    Registers the shared limiter, the 429 handler, and the middleware that
    applies `default_limits` to every non-exempt route.

    Args:
        app: FastAPI application instance

    Returns:
        Configured Limiter instance
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    return limiter
