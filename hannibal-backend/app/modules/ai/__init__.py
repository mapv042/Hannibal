"""AI module for LLM-powered intent detection and conversational responses."""

from __future__ import annotations

from app.modules.ai.base_service import BaseAIService


def get_ai_service() -> BaseAIService:
    """Factory that returns the AI service based on the ai_provider setting."""
    from app.config import settings

    if settings.ai_provider == "anthropic":
        from app.modules.ai.anthropic_service import AnthropicService
        return AnthropicService()

    from app.modules.ai.openai_service import OpenAIService, is_reasoning_first_model

    # Reasoning-first models can only combine reasoning with function tools on
    # /v1/responses; on /v1/chat/completions OpenAI rejects the pair.
    if is_reasoning_first_model(settings.open_ai_model):
        from app.modules.ai.openai_responses_service import OpenAIResponsesService
        return OpenAIResponsesService()

    return OpenAIService()
