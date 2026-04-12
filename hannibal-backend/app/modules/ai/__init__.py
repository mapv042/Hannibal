"""AI module for LLM-powered intent detection and conversational responses."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.ai.openai_service import OpenAIService
    from app.modules.ai.anthropic_service import AnthropicService


def get_ai_service() -> OpenAIService | AnthropicService:
    """Factory that returns the AI service based on the ai_provider setting."""
    from app.config import settings

    if settings.ai_provider == "anthropic":
        from app.modules.ai.anthropic_service import AnthropicService
        return AnthropicService()

    from app.modules.ai.openai_service import OpenAIService
    return OpenAIService()
