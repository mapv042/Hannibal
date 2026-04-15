"""AI module for LLM-powered intent detection and conversational responses."""

from __future__ import annotations

from app.modules.ai.base_service import BaseAIService


def get_ai_service() -> BaseAIService:
    """Factory that returns the AI service based on the ai_provider setting."""
    from app.config import settings

    if settings.ai_provider == "anthropic":
        from app.modules.ai.anthropic_service import AnthropicService
        return AnthropicService()

    from app.modules.ai.openai_service import OpenAIService
    return OpenAIService()
