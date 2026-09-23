"""AI module: the tool-use conversation services and how one is chosen."""

from __future__ import annotations

from app.core.ai_selection import current_selection
from app.modules.ai.base_service import BaseAIService


def get_ai_service() -> BaseAIService:
    """Build the AI service this turn should use.

    The provider and model normally come from configuration; inside a simulator
    run they can be overridden per request, which is what makes comparing two
    models a button rather than a redeploy (see app/core/ai_selection.py).
    """
    provider, model = current_selection()

    if provider == "anthropic":
        from app.modules.ai.anthropic_service import AnthropicService

        return AnthropicService(model=model)

    from app.modules.ai.openai_service import OpenAIService, is_reasoning_first_model

    # Reasoning-first models can only combine reasoning with function tools on
    # /v1/responses; on /v1/chat/completions OpenAI rejects the pair. The check
    # is on the chosen model, not the configured one, so an overridden model gets
    # routed to the right endpoint too.
    if is_reasoning_first_model(model):
        from app.modules.ai.openai_responses_service import OpenAIResponsesService

        return OpenAIResponsesService(model=model)

    return OpenAIService(model=model)
