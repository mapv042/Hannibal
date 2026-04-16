from __future__ import annotations

from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Database
    database_url: str

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # AI provider: "openai" or "anthropic"
    ai_provider: str = "openai"

    # Anthropic
    anthropic_api_key: str = ""

    # OpenAI
    open_ai_key: str = ""

    # Meta/WhatsApp
    meta_verify_token: str = ""
    meta_app_secret: str = ""
    meta_app_id: str = ""

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    # Security
    encryption_key: str = "0" * 64  # 64-char hex for AES-256
    jwt_secret: str = ""

    # Error tracking (optional)
    sentry_dsn: str | None = None

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    confirmation_request_hour: int = 8  # Hour (0-23) to send confirmation requests (Mexico City TZ)
    confirmation_request_minute: int = 0  # Minute (0-59) to send confirmation requests
    earliest_reminder_hour: int = 8  # Don't send reminders before this hour (Mexico City TZ)

    # AI mode: use tool-based conversation (v2) instead of intent/state-machine (v1)
    use_tool_based_ai: bool = False

    # Frontend
    frontend_url: str = "http://localhost:3000"

    @computed_field
    @property
    def async_database_url(self) -> str:
        """Ensure the database URL always uses the asyncpg driver."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif not url.startswith("postgresql+asyncpg://"):
            url = f"postgresql+asyncpg://{url}"
        return url

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
    }


settings = Settings()
