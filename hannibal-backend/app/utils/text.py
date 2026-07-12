"""Text helpers for safely embedding user-controlled data into prompts."""

from __future__ import annotations

DEFAULT_PROMPT_FIELD_MAX = 120


def sanitize_for_prompt(value: str | None, max_len: int = DEFAULT_PROMPT_FIELD_MAX) -> str:
    """Neutralize a user-controlled string before putting it in an LLM prompt.

    Patient-supplied fields (name, urgency reason) flow into the doctor/patient
    system prompt. Without cleaning, a patient could register a "name" carrying
    injected instructions ("ignora tus reglas y..."). This collapses newlines
    (the main lever for faking new prompt sections), strips control characters
    and caps length. It is defense-in-depth, not a full guarantee — keep
    treating tool results, not free text, as the source of truth.
    """
    if not value:
        return ""
    # Collapse any whitespace run (including newlines/tabs) into single spaces.
    cleaned = " ".join(str(value).split())
    # Drop remaining control characters.
    cleaned = "".join(ch for ch in cleaned if ch.isprintable())
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip() + "…"
    return cleaned
