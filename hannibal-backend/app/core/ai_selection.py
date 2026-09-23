"""Which model answers this turn.

Normally the answer is fixed by configuration: `AI_PROVIDER` and the matching
model setting, decided per deployment. That is fine for running the product and
useless for the question the simulator exists to answer — *which model should we
use?* — because comparing two models would mean a redeploy between every run.

So the selection can be overridden for the current request. The override lives in
a ContextVar for the same reasons the clock's offset does: it is read deep inside
code that has no business taking a model argument (the conversation managers
build their AI service themselves), threading it through would mean widening the
webhook's whole call chain, and two concurrent runs must not see each other's
choice.

It is inert outside a simulator run, so production always uses its configured
model and cannot be talked into another one by a stray header.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import NamedTuple, Optional


class AISelection(NamedTuple):
    """The provider and model a turn should use."""

    provider: str
    model: str


_override: ContextVar[Optional[AISelection]] = ContextVar("ai_override", default=None)


def set_ai_override(provider: str, model: str) -> None:
    """Pin this request's provider and model.

    Args:
        provider: "openai" or "anthropic".
        model: The model id to send.

    Raises:
        ValueError: On an unknown provider, so a typo in the simulator's UI fails
            here rather than as a confusing error from the wrong SDK.
    """
    if provider not in ("openai", "anthropic"):
        raise ValueError(f"unknown AI provider: {provider!r}")
    if not model:
        raise ValueError("a model id is required")

    _override.set(AISelection(provider=provider, model=model))


def clear_ai_override() -> None:
    """Fall back to the configured provider and model."""
    _override.set(None)


def current_selection() -> AISelection:
    """The provider and model this turn should use.

    Returns the override when a simulator run set one, else what the environment
    is configured with.
    """
    from app.config import settings
    from app.core.clock import simulation_enabled

    chosen = _override.get()
    if chosen is not None and simulation_enabled():
        return chosen

    provider = settings.ai_provider
    model = (
        settings.anthropic_ai_model
        if provider == "anthropic"
        else settings.open_ai_model
    )
    return AISelection(provider=provider, model=model)
