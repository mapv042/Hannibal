"""Text helpers: safely embedding user text into prompts, reading plain yes/no."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

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


_YES = {"si", "acepto", "si acepto", "de acuerdo", "estoy de acuerdo", "ok", "okay", "va",
        "claro", "sale", "si lo quiero", "lo quiero", "si por favor", "si gracias"}
_NO = {"no", "no acepto", "no estoy de acuerdo", "no gracias", "no lo quiero"}


def normalize_reply(text: str) -> str:
    """Lowercase, accents and punctuation stripped, single spaces: "¡Sí, acepto!" → "si acepto"."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z ]", " ", text).split())


def plain_yes_no(text: str) -> Optional[bool]:
    """A short, plain yes/no to a question the system asked; None for anything else.

    Deliberately strict — "sí, pero mejor el martes" is not a yes to the
    question, it is a new request for the assistant to handle.
    """
    normalized = normalize_reply(text)
    if normalized in _YES:
        return True
    if normalized in _NO:
        return False
    return None

