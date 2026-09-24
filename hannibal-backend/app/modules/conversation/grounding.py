"""Deterministic checks on the assistant's final reply, before it is sent.

The prompt asks the model not to invent; this module makes sure it didn't. Each
check compares the reply against *evidence* — what the tools returned this
turn, what ConversationState recorded in earlier turns, and what the user and
the office config said — and reports what the reply asserts without backing:

- claimed_action: the reply says an appointment was booked / cancelled / moved
  / confirmed, or the doctor was notified, but no successful tool call backs
  that kind of action (TOOL_CLAIMS / DOCTOR_TOOL_CLAIMS declare what each write
  backs). This is "dijo que lo hizo y no lo hizo".
- unsupported_time: the reply mentions a clock time that appears nowhere in the
  evidence. This is the invented "tengo a las 11:30".
- weekday_mismatch: "jueves 24" when the 24th is a Friday.

The tool loop (base_manager.run_tool_loop) feeds violations back to the model
for one corrective pass. The checks are a plain list: adding one means writing
a function with the same signature and appending it to CHECKS.

The patterns are deliberately conservative. A missed violation costs what it
cost before this module existed; a false positive costs one extra model call.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Iterable, Optional

from app.core.constants import DAYS_ES, MONTHS_ES


@dataclass
class Violation:
    kind: str
    detail: str  # Spanish, fed back to the model

    def as_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


@dataclass
class Evidence:
    """Everything a reply may legitimately draw facts from."""

    today: date
    # Claim kinds backed by a successful write (this turn or earlier ones).
    claims: set[str] = field(default_factory=set)
    # Minutes-of-day of every clock time found in the evidence texts.
    known_minutes: set[int] = field(default_factory=set)

    @classmethod
    def build(
        cls,
        *,
        today: date,
        claims: Iterable[str],
        texts: Iterable[str],
    ) -> "Evidence":
        known: set[int] = set()
        for text in texts:
            known |= evidence_minutes(text)
        return cls(today=today, claims=set(claims), known_minutes=known)


def _fold(text: str) -> str:
    """Lowercase and strip accents, for accent-insensitive matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


# ---------------------------------------------------------------------------
# Times
# ---------------------------------------------------------------------------

# "4:00 PM", "4 pm", "4:30 p.m.", "16:00", "16:00 hrs". A bare "a las 4" is
# not matched: without minutes or a meridiem it's too ambiguous to police.
_TIME_RE = re.compile(
    r"\b(?P<h>[01]?\d|2[0-3])(?::(?P<m>[0-5]\d))?\s*(?P<ap>a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z])"
    r"|\b(?P<h24>[01]?\d|2[0-3]):(?P<m24>[0-5]\d)\b",
    re.IGNORECASE,
)


def _time_matches(text: str) -> list[tuple[str, set[int]]]:
    """(matched text, candidate minutes-of-day) for each time in `text`."""
    out = []
    for m in _TIME_RE.finditer(text):
        if m.group("ap"):
            h = int(m.group("h"))
            minute = int(m.group("m") or 0)
            if not 1 <= h <= 12:
                continue
            pm = m.group("ap").lower().startswith("p")
            h24 = (h % 12) + (12 if pm else 0)
            out.append((m.group(0), {h24 * 60 + minute}))
        else:
            h = int(m.group("h24"))
            minute = int(m.group("m24"))
            # A colon time without a meridiem may be either half of the day.
            cands = {h * 60 + minute}
            if 1 <= h <= 11:
                cands.add((h + 12) * 60 + minute)
            out.append((m.group(0), cands))
    return out


# Also accept the bare hours a user types ("a las 4", "tipo 5"), as evidence
# only — so a reply echoing the user's own proposed time isn't flagged.
_BARE_HOUR_RE = re.compile(r"\b(?:a las|a la|las|tipo|como a las)\s+(\d{1,2})\b", re.IGNORECASE)


def evidence_minutes(text: str) -> set[int]:
    """Every minute-of-day a text supports (both halves of the day if ambiguous)."""
    if not text:
        return set()
    minutes: set[int] = set()
    for _, cands in _time_matches(text):
        minutes |= cands
    for m in _BARE_HOUR_RE.finditer(text):
        h = int(m.group(1))
        if 1 <= h <= 12:
            minutes |= {(h % 12) * 60, ((h % 12) + 12) * 60}
    # Slot ids / ISO datetimes: 2026-09-24T16:00
    for m in re.finditer(r"\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})", text):
        minutes.add(int(m.group(1)) * 60 + int(m.group(2)))
    return minutes


def check_unsupported_time(reply: str, ev: Evidence) -> list[Violation]:
    bad = [
        raw for raw, cands in _time_matches(reply)
        if not (cands & ev.known_minutes)
    ]
    if not bad:
        return []
    return [Violation(
        "unsupported_time",
        "Mencionaste horarios que ninguna herramienta te dio: "
        + ", ".join(sorted(set(bad)))
        + ". Solo puedes dar horarios que salieron de las herramientas "
        "(consúltalas si hace falta).",
    )]


# ---------------------------------------------------------------------------
# Claimed actions
# ---------------------------------------------------------------------------

# Patterns run on the lowercased reply WITH its accents: the accent is what
# tells the completed first-person "agendé" from the subjunctive "¿quieres que
# te agende?", and the models write accents reliably. Only completed-action
# forms are listed: "quedó agendada", "cancelé", "ya le avisé".
_CLAIM_PATTERNS: dict[str, list[str]] = {
    "book": [
        r"\bqued[oó]\s+(agendad|registrad|reservad|programad)",
        r"\bquedaron\s+(agendad|registrad|reservad|programad)",
        r"\bagendé\b",
        r"\bya\s+(está|están)\s+agendad",
        r"\bhe\s+agendado\b",
        r"\b(fue|ha\s+sido)\s+agendad",
    ],
    "cancel": [
        r"\bqued[oó]\s+cancelad",
        r"\bquedaron\s+cancelad",
        r"\bcancelé\b",
        r"\bya\s+(está|están)\s+cancelad",
        r"\bhe\s+cancelado\b",
        r"\b(fue|ha\s+sido)\s+cancelad",
    ],
    "reschedule": [
        r"\bqued[oó]\s+(reagendad|cambiad)",
        r"\bquedaron\s+reagendad",
        r"\breagendé\b",
        r"\bya\s+(está|están)\s+reagendad",
        r"\bhe\s+reagendado\b",
        r"\b(fue|ha\s+sido)\s+(reagendad|movid)",
        r"\bmoví\s+(tu|la|su)\s+cita\b",
    ],
    "confirm_attendance": [
        r"\basistencia\s+(qued[oó]|está)\s+confirmad",
        r"\bconfirmé\s+(tu|su)\s+asistencia\b",
    ],
    "notify_doctor": [
        r"\b(avisé|notifiqué|informé)\s+al\s+(doctor|dr\.?|médico)",
        r"\bel\s+(doctor|dr\.?)\s+ya\s+(fue\s+)?(avisado|notificado)",
    ],
    "message_sent": [
        r"\bmensajes?\s+(fue\s+|fueron\s+)?enviados?\b",
        r"\b(envié|mandé)\s+(el|los)\s+mensajes?\b",
        r"\bya\s+(se\s+lo|se\s+los|le|les)\s+(envié|mandé)\b",
    ],
}
_COMPILED_CLAIMS = {k: [re.compile(p) for p in v] for k, v in _CLAIM_PATTERNS.items()}
_NEGATION_RE = re.compile(r"\b(no|nunca|aún no|aun no|todavía no|sin)\s+(\S+\s+){0,2}$")

_CLAIM_LABELS = {
    "book": "que agendaste una cita",
    "cancel": "que cancelaste una cita",
    "reschedule": "que reagendaste una cita",
    "confirm_attendance": "que confirmaste la asistencia",
    "notify_doctor": "que avisaste al doctor",
    "message_sent": "que el mensaje se envió",
}


def claimed_kinds(reply: str) -> set[str]:
    """The action kinds the reply asserts as done."""
    text = reply.lower()
    kinds = set()
    for kind, patterns in _COMPILED_CLAIMS.items():
        for p in patterns:
            for m in p.finditer(text):
                before = text[max(0, m.start() - 25):m.start()]
                if _NEGATION_RE.search(before):
                    continue
                kinds.add(kind)
                break
            if kind in kinds:
                break
    return kinds


def check_claimed_action(reply: str, ev: Evidence) -> list[Violation]:
    unbacked = sorted(k for k in claimed_kinds(reply) if k not in ev.claims)
    if not unbacked:
        return []
    return [Violation(
        "claimed_action",
        "Tu respuesta afirma "
        + " y ".join(_CLAIM_LABELS[k] for k in unbacked)
        + ", pero ninguna herramienta lo hizo. No afirmes una acción que no ejecutaste: "
        "dile al usuario lo que realmente pasó y lo que falta. Ejecuta una acción solo si el "
        "usuario ya la pidió o aprobó explícitamente.",
    )]


# ---------------------------------------------------------------------------
# Weekday / date consistency
# ---------------------------------------------------------------------------

_DAY_NAMES_FOLDED = [_fold(d) for d in DAYS_ES]
_MONTHS_FOLDED = [_fold(m) for m in MONTHS_ES]
_WEEKDAY_DATE_RE = re.compile(
    # The day number must not be the hour of a time: "viernes 10:00 AM" and
    # "jueves 11 AM" are a weekday and a time, not the 10th and the 11th.
    r"\b(" + "|".join(_DAY_NAMES_FOLDED) + r")\s+(\d{1,2})(?![\d:])(?!\s*[ap]\.?\s?m\b)"
    r"(?:\s+de\s+(" + "|".join(_MONTHS_FOLDED) + r"))?"
    r"(?:\s*/\s*(\d{1,2})(?:\s*/\s*(\d{4}))?)?"
)


def _candidates(day: int, month: Optional[int], year: Optional[int], today: date) -> list[date]:
    """Plausible dates for 'jueves 24' (month/year optional)."""
    out = []
    if month and year:
        try:
            return [date(year, month, day)]
        except ValueError:
            return []
    if month:
        # "24 de septiembre" is the next one to come (or one just past), never
        # both this year's and next year's — that would excuse any weekday.
        for y in (today.year, today.year + 1):
            try:
                d = date(y, month, day)
            except ValueError:
                continue
            if (d - today).days >= -45:
                return [d]
        return out
    # No month: this month, the next and the previous one.
    first = today.replace(day=1)
    for delta in (-1, 0, 1, 2):
        y = first.year + (first.month - 1 + delta) // 12
        mth = (first.month - 1 + delta) % 12 + 1
        try:
            out.append(date(y, mth, day))
        except ValueError:
            pass
    return out


def check_weekday_mismatch(reply: str, ev: Evidence) -> list[Violation]:
    folded = _fold(reply)
    wrong = []
    for m in _WEEKDAY_DATE_RE.finditer(folded):
        weekday = _DAY_NAMES_FOLDED.index(m.group(1))
        day = int(m.group(2))
        month = None
        year = None
        if m.group(3):
            month = _MONTHS_FOLDED.index(m.group(3)) + 1
        elif m.group(4):
            month = int(m.group(4))
            year = int(m.group(5)) if m.group(5) else None
        if not 1 <= day <= 31 or (month is not None and not 1 <= month <= 12):
            continue
        cands = _candidates(day, month, year, ev.today)
        # Only dates near today are what a conversation is about.
        near = [c for c in cands if -45 <= (c - ev.today).days <= 400]
        if month is None:
            # Without a month, "martes 29" can only mean a nearby 29th.
            near = [c for c in near if (c - ev.today).days <= 75]
        if near and not any(c.weekday() == weekday for c in near):
            wrong.append(m.group(0))
    if not wrong:
        return []
    return [Violation(
        "weekday_mismatch",
        "El día de la semana no corresponde a la fecha en: "
        + ", ".join(wrong)
        + ". Toma el día y la fecha del CALENDARIO DE REFERENCIA o del resultado de la "
        "herramienta, tal cual.",
    )]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

Check = Callable[[str, Evidence], list[Violation]]

CHECKS: list[Check] = [
    check_claimed_action,
    check_unsupported_time,
    check_weekday_mismatch,
]


def validate_reply(reply: str, evidence: Evidence) -> list[Violation]:
    """Run every check; an empty list means the reply is grounded."""
    if not reply or not reply.strip():
        return []
    violations: list[Violation] = []
    for check in CHECKS:
        violations.extend(check(reply, evidence))
    return violations


def tool_result_texts(results: Iterable[dict]) -> list[str]:
    """Serialize tool results so their times count as evidence."""
    return [json.dumps(r, ensure_ascii=False, default=str) for r in results]


# Prefix of the correction note. The note quotes the offending times, so the
# evidence builder must skip it — otherwise the second check finds the very
# times it's checking "in the evidence".
CORRECTION_PREFIX = "[Nota interna del sistema — el usuario NO la ve]"


def correction_message(violations: list[Violation]) -> str:
    """The internal note fed back to the model for its corrective pass."""
    lines = [
        f"{CORRECTION_PREFIX} Tu respuesta anterior no se envió porque tiene errores:",
    ]
    lines += [f"- {v.detail}" for v in violations]
    lines.append(
        "Escribe de nuevo tu respuesta al usuario corrigiendo esto (usa herramientas si lo "
        "necesitas). No menciones esta nota."
    )
    return "\n".join(lines)
