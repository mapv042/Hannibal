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
    # Token ceiling for one assistant turn, across providers. With reasoning on,
    # the model's thinking is billed and counted against this too, so a turn can
    # be truncated well before the reply itself gets long.
    ai_max_output_tokens: int = 4096

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_ai_model: str = ""

    # OpenAI
    open_ai_key: str = ""
    open_ai_model: str = ""
    # Sent only to reasoning-first models (gpt-5.6+, o-series); empty = never
    # send. On /v1/chat/completions "none" is the only value those models accept
    # alongside function tools, and the whole conversation flow is tool-use —
    # real reasoning + tools would require migrating to /v1/responses.
    open_ai_reasoning_effort: str = "none"

    # Meta/WhatsApp
    meta_verify_token: str = ""
    meta_app_secret: str = ""
    meta_app_id: str = ""
    # Two-step verification PIN sent when registering a number for Cloud API
    # during Embedded Signup. If the number already has a 2FA PIN, Meta requires
    # that exact PIN, so keep this stable once doctors are onboarded.
    meta_register_pin: str = "000000"

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
    # Patient-facing sending window (Mexico City TZ). A reminder whose offset
    # lands outside it is moved to the edge of the window, never sent at night.
    earliest_reminder_hour: int = 8  # Don't send reminders before this hour
    latest_reminder_hour: int = 21  # Don't send reminders after this hour

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
