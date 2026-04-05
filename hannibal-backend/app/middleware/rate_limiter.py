"""Rate limiting middleware using slowapi."""

from __future__ import annotations

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import FastAPI


def setup_rate_limiter(app: FastAPI) -> Limiter:
    """
    Setup rate limiting for the FastAPI application.

    Args:
        app: FastAPI application instance

    Returns:
        Configured Limiter instance
    """
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    return limiter


# Rate limit definitions for different endpoint types
WEBHOOK_LIMIT = "100/minute"  # WhatsApp and other webhooks
API_LIMIT = "30/minute"  # Standard API endpoints
AUTH_LIMIT = "5/minute"  # Authentication endpoints
