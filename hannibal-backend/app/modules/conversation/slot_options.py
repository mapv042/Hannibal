"""Offered slots as WhatsApp buttons or a list, instead of times in the text.

To offer slots the patient model writes each one as a marker with its exact id
(`[[2026-09-24T16:00]]`) rather than its time. This module turns a reply into
what each reader needs:

- the patient reads the text without the markers, and taps a slot: up to
  MAX_BUTTONS as reply buttons on the message itself, more behind a "Ver
  horarios" list — which holds MAX_LIST_ROWS at most, so a longer offer (a
  whole free day) shows that many spread across it, plus a note that there
  are more;
- the model's history keeps the slots written out ("4:00 PM y 5:00 PM"),
  because history is plain text: with only the markers stripped, next turn it
  wouldn't know what it offered.

A marker is honoured only for a slot an availability tool returned
(ConversationState.offered_slots) — the button is built from the tool's own
labels, never from anything the model wrote. Markers for anything else are
dropped here and flagged by the reply validator (grounding.check_slot_markers).

A tapped option comes back with its id (`slot:<slot_id>`), which the message
extraction turns into text carrying the exact slot_id for prepare_booking.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional

from app.core.constants import DAYS_ES, MONTHS_ES
from app.modules.ai.tool_helpers import format_appointment_dt, parse_slot_id
from app.modules.conversation.state import OfferedSlot
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Meta's limits: 3 reply buttons, 10 list rows, 20-char button titles, 24-char
# row and section titles, 1024-char interactive body.
MAX_BUTTONS = 3
MAX_LIST_ROWS = 10
MAX_INTERACTIVE_BODY = 1024
LIST_BUTTON_TEXT = "Ver horarios"
# Body for the interactive message when the reply itself had to go out as text.
SHORT_BODY = "Elige un horario:"
# Appended when the list can't hold every slot the reply offered.
MORE_SLOTS_NOTE = "Te muestro algunos; si buscas otra hora, dime cuál."

# Prefix of a tapped option's id; the rest is the slot_id.
SLOT_REPLY_PREFIX = "slot:"

MARKER_RE = re.compile(r"\[\[\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})\s*\]\]")
# A run of markers with what models put between them ("[[a]], [[b]] y [[c]]",
# one per bullet line): it is removed or rewritten as one piece.
_MARKER_RUN_RE = re.compile(
    r"(?:\[\[\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\s*\]\])"
    r"(?:[ \t]*(?:,|;|\by\b|\bo\b|/|\n[ \t]*(?:[-*•]|\d+[.)])?)?[ \t]*"
    r"\[\[\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\s*\]\])*"
)

Presentation = Literal["text", "buttons", "list"]


@dataclass
class SlotReply:
    """One reply, as the patient sees it and as the model remembers it."""

    text: str  # what the patient reads
    history_text: str  # what goes into the session history, the DB and the trace
    kind: Presentation = "text"
    options: list[OfferedSlot] = field(default_factory=list)

    def buttons(self) -> list[dict[str, str]]:
        return [{"id": SLOT_REPLY_PREFIX + s.slot_id, "title": button_title(s)} for s in self.options]

    def options_in_words(self) -> str:
        """The options as plain text, for when they can't go out as buttons."""
        return _in_words(self.options)

    def sections(self) -> list[dict]:
        """List rows grouped by day, in the order the reply offered them."""
        sections: list[dict] = []
        for s in self.options:
            title = section_title(s)
            if not sections or sections[-1]["title"] != title:
                sections.append({"title": title, "rows": []})
            sections[-1]["rows"].append(
                {"id": SLOT_REPLY_PREFIX + s.slot_id, "title": s.time_label[:24]}
            )
        return sections


def markers_in(text: str) -> list[str]:
    """Slot ids of every marker in `text`, in order, without repeats."""
    seen: list[str] = []
    for slot_id in MARKER_RE.findall(text or ""):
        if slot_id not in seen:
            seen.append(slot_id)
    return seen


def present(reply: str, offered: Iterable[OfferedSlot]) -> SlotReply:
    """Split a reply into the patient's text + tappable options and the history text."""
    if not MARKER_RE.search(reply or ""):
        return SlotReply(text=reply, history_text=reply)

    by_id = {s.slot_id: s for s in offered}
    options = [by_id[i] for i in markers_in(reply) if i in by_id]
    written = _rewrite(reply, by_id, keep=True)

    if not options:
        return SlotReply(text=written, history_text=written)

    return offer(_rewrite(reply, by_id, keep=False), options, history_text=written)


def offer(text: str, options: list[OfferedSlot], history_text: Optional[str] = None) -> SlotReply:
    """A message offering `options` as buttons (≤3) or a list.

    `history_text` defaults to the text followed by the slots in words.
    """
    if history_text is None:
        history_text = f"{text} {_in_words(options, context=text)}".strip()
    if len(options) > MAX_LIST_ROWS:
        # A whole free day doesn't fit: show a spread of it. The history keeps
        # every slot, so "¿y a las 3:40?" is still one the model offered.
        options = _spread(options, MAX_LIST_ROWS)
        text = f"{text}\n\n{MORE_SLOTS_NOTE}".strip()
    return SlotReply(
        text=text,
        history_text=history_text,
        kind="buttons" if len(options) <= MAX_BUTTONS else "list",
        options=options,
    )


async def send_reply(meta_client, office, to: str, reply: SlotReply) -> str:
    """Send a reply; its slots go out as reply buttons or a list.

    If the interactive message is refused, the slots still reach the patient,
    written out in plain text. Raises only if the plain text fails too.
    """

    async def send_text(text: str) -> str:
        return await meta_client.send_text_message(
            phone_number_id=office.whatsapp_phone_id,
            token=office.whatsapp_token,
            to=to,
            text=text,
        )

    if reply.kind == "text":
        return await send_text(reply.text)

    body = reply.text
    text_sent = False
    try:
        if not body or len(body) > MAX_INTERACTIVE_BODY:
            # Too long for an interactive body: the words go first, the
            # options follow under a short prompt.
            if body:
                await send_text(body)
                text_sent = True
            body = SHORT_BODY
        if reply.kind == "buttons":
            message_id = await meta_client.send_interactive_buttons(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=to,
                body_text=body,
                buttons=reply.buttons(),
            )
        else:
            message_id = await meta_client.send_interactive_list(
                phone_number_id=office.whatsapp_phone_id,
                token=office.whatsapp_token,
                to=to,
                body_text=body,
                button_text=LIST_BUTTON_TEXT,
                sections=reply.sections(),
            )
        logger.info(
            "slot_options_sent",
            office_id=str(office.id),
            kind=reply.kind,
            count=len(reply.options),
        )
        return message_id
    except Exception as e:
        logger.warning(
            "slot_options_send_failed",
            office_id=str(office.id),
            kind=reply.kind,
            error=str(e),
        )
        if text_sent:
            return await send_text(reply.options_in_words())
        return await send_text(reply.history_text)


def slot_choice_text(reply_id: str, title: str) -> Optional[str]:
    """What the model reads when the patient taps a slot option; None if it isn't one."""
    if not (reply_id or "").startswith(SLOT_REPLY_PREFIX):
        return None
    slot_id = reply_id[len(SLOT_REPLY_PREFIX):]
    when = parse_slot_id(slot_id)
    if isinstance(when, dict):
        return None
    return f"[El paciente eligió de las opciones: {format_appointment_dt(when)} — slot_id {slot_id}]"


def button_title(slot: OfferedSlot) -> str:
    """'Jue 24 · 4:00 PM' — fits Meta's 20 characters."""
    when = parse_slot_id(slot.slot_id)
    if isinstance(when, dict):
        return slot.time_label[:20]
    day = DAYS_ES[when.weekday()][:3].capitalize()
    return f"{day} {when.day} · {slot.time_label}"[:20]


def section_title(slot: OfferedSlot) -> str:
    """'Jueves 24 sep' — fits Meta's 24 characters."""
    when = parse_slot_id(slot.slot_id)
    if isinstance(when, dict):
        return slot.date_label[:24]
    return f"{DAYS_ES[when.weekday()].capitalize()} {when.day} {MONTHS_ES[when.month - 1][:3]}"[:24]


def _rewrite(reply: str, by_id: dict[str, OfferedSlot], keep: bool) -> str:
    """Replace each run of markers: by its slots in words (keep) or by nothing."""

    def replace(match: re.Match) -> str:
        if not keep:
            return ""
        slots = [by_id[i] for i in markers_in(match.group(0)) if i in by_id]
        return _in_words(slots, context=reply)

    text = _MARKER_RUN_RE.sub(replace, reply)
    return _tidy(text)


def _in_words(slots: list[OfferedSlot], context: str = "") -> str:
    """'jueves 24 de septiembre: 4:00 PM y 5:00 PM; viernes 25 de septiembre: 10:00 AM'.

    Slots of a single day that `context` (the reply) already names are just
    their times: "El lunes 9 de noviembre tengo 9:00 AM y 9:40 AM", not "El
    lunes 9 de noviembre tengo lunes 9 de noviembre: …".
    """
    days: list[tuple[str, list[str]]] = []
    for s in slots:
        if not days or days[-1][0] != s.date_label:
            days.append((s.date_label, []))
        days[-1][1].append(s.time_label)
    if len(days) == 1 and _fold(days[0][0]) in _fold(context):
        return _join(days[0][1])
    return "; ".join(f"{label}: {_join(times)}" for label, times in days)


def _spread(options: list[OfferedSlot], k: int) -> list[OfferedSlot]:
    """`k` of `options` evenly spread, first and last included, order kept."""
    n = len(options)
    return [options[round(i * (n - 1) / (k - 1))] for i in range(k)]


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def _tidy(text: str) -> str:
    """Clean up what removing markers leaves behind: bare bullets, gaps, ' .'."""
    # A bullet whose marker was removed leaves a bare "-" or "1." line.
    lines = [
        line.rstrip() for line in text.split("\n")
        if not re.fullmatch(r"\s*(?:[-*•]|\d+[.)])\s*", line)
    ]
    text = "\n".join(lines)
    text = re.sub(r"[ \t]+([,.;:?!])", r"\1", text)
    # "tengo estos horarios: [[…]]." without its markers is "horarios:."
    text = re.sub(r":[ \t]*[.,;]", ":", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
