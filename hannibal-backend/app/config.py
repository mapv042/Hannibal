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
    anthropic_ai_model: str = ""

    # OpenAI
    open_ai_key: str = ""
    open_ai_model: str = ""

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

    # Deployment environment: "development" | "production". In production the
    # app refuses to start with placeholder/empty secrets (see validate_secrets).
    environment: str = "development"

    # Security
    encryption_key: str = "0" * 64  # 64-char hex for AES-256
    jwt_secret: str = ""
    # Supabase signs access tokens with aud="authenticated"; verified on decode.
    jwt_audience: str = "authenticated"

    # Error tracking (optional)
    sentry_dsn: str | None = None

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    confirmation_request_hour: int = 8  # Hour (0-23) to send confirmation requests (Mexico City TZ)
    confirmation_request_minute: int = 0  # Minute (0-59) to send confirmation requests
    earliest_reminder_hour: int = 8  # Don't send reminders before this hour (Mexico City TZ)

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # Backend public URL (used to build the Google Calendar push webhook address)
    backend_url: str = ""

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

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")

    def validate_secrets(self) -> None:
        """Fail fast if a security-critical secret is empty/placeholder.

        An empty JWT_SECRET makes tokens forgeable, and the default all-zero
        ENCRYPTION_KEY makes "encrypted" data trivially decryptable — so in
        production we refuse to start rather than run wide open. Called at app
        startup (see main.lifespan).
        """
        problems = []
        if not self.jwt_secret:
            problems.append("JWT_SECRET is empty")
        if self.encryption_key == "0" * 64:
            problems.append("ENCRYPTION_KEY is the insecure default")
        else:
            # A malformed key passes the default check but makes every
            # encrypted-column WRITE raise at flush time (reads fall back to
            # plaintext), poisoning sessions mid-request — fail at boot instead.
            try:
                if len(bytes.fromhex(self.encryption_key)) != 32:
                    problems.append("ENCRYPTION_KEY must be 64 hex chars (32 bytes) — generate with: openssl rand -hex 32")
            except ValueError:
                problems.append("ENCRYPTION_KEY is not valid hex — generate with: openssl rand -hex 32")
        if not self.meta_app_secret:
            problems.append("META_APP_SECRET is empty (webhook signatures cannot be verified)")

        if problems:
            message = "Insecure configuration: " + "; ".join(problems)
            if self.is_production:
                raise RuntimeError(message)
            # In development, warn loudly but allow the app to run.
            import warnings
            warnings.warn(message, stacklevel=2)

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
    }


settings = Settings()
