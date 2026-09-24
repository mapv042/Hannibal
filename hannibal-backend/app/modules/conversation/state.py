"""Structured working memory of a conversation, carried between turns.

Persisted history is plain text only (see BaseToolConversationManager): the tool
chain of a turn is discarded once the turn ends, because it is provider-specific.
That kept sessions portable, but it also meant the model's only record of what
happened in earlier turns was its own prose. It re-read "te ofrezco el jueves a
las 4:00 PM" and rebuilt the date and the 24-hour time from it — which is where
"la opción 2" became the wrong slot, "las 4" became 04:00, and "listo, quedó
agendada" was taken as proof of a booking that never happened.

ConversationState is the fix: the facts the tools established — the slots that
were offered (with their exact ids), the patient's appointments, a booking
awaiting the patient's yes, and every write that was executed — are stored as
data and rendered into the dynamic part of the prompt on every turn. It is
provider-agnostic plain text, so switching AI_PROVIDER still never breaks a
live session.

This is memory, not a state machine: there are no transitions and no intents.
Handlers record facts; the model reads them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.constants import MX_TIMEZONE
from app.utils.text import sanitize_for_prompt

# Enough to cover a week of offered slots without the prompt block growing
# unbounded when the model sweeps several days.
MAX_OFFERED_SLOTS = 40
# A doctor's batch instruction (reschedule five citas, draft five notices) must
# not push the first actions out before the reply that reports them.
MAX_RECENT_ACTIONS = 12


class OfferedSlot(BaseModel):
    """A slot an availability tool returned. `slot_id` is 'YYYY-MM-DDTHH:MM'."""

    slot_id: str
    date_label: str
    time_label: str


class KnownAppointment(BaseModel):
    """An appointment the tools reported, as of the last lookup."""

    id: str
    label: str
    status: str
    patient_name: Optional[str] = None


class BookingDraft(BaseModel):
    """A booking validated by prepare_booking, awaiting the patient's yes.

    confirm_booking writes exactly this — the model cannot change the date or
    time between the summary the patient approved and the write.
    """

    slot_id: str
    label: str
    summary: str
    patient_name: str
    patient_phone: Optional[str] = None
    for_self: bool = True
    reason: str
    intake_notes: Optional[str] = None
    replaces_appointment_id: Optional[str] = None
    confirm_second_same_day: bool = False
    created_at: str


class ActionRecord(BaseModel):
    """A write a tool executed, summarized by code (not by the model)."""

    tool: str
    ok: bool
    summary: str
    # What this action lets the assistant truthfully claim ("book", "cancel",
    # …) — read by the reply validator (grounding.py).
    claims: list[str] = Field(default_factory=list)
    at: str


class ConversationState(BaseModel):
    offered_slots: list[OfferedSlot] = Field(default_factory=list)
    known_appointments: list[KnownAppointment] = Field(default_factory=list)
    draft: Optional[BookingDraft] = None
    recent_actions: list[ActionRecord] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Mutators (called by tool handlers and the tool loop)
    # ------------------------------------------------------------------

    def remember_slots(self, slots: list[OfferedSlot]) -> None:
        """Add slots from an availability lookup (newest last, deduped)."""
        by_id = {s.slot_id: s for s in self.offered_slots}
        for s in slots:
            by_id.pop(s.slot_id, None)
            by_id[s.slot_id] = s
        self.offered_slots = list(by_id.values())[-MAX_OFFERED_SLOTS:]

    def remember_appointments(self, appointments: list[KnownAppointment]) -> None:
        """Replace the known appointments with a fresh lookup."""
        self.known_appointments = list(appointments)

    def record_action(
        self, tool: str, ok: bool, summary: str, claims: list[str], at: datetime
    ) -> None:
        self.recent_actions.append(
            ActionRecord(
                tool=tool, ok=ok, summary=summary, claims=claims, at=at.isoformat()
            )
        )
        self.recent_actions = self.recent_actions[-MAX_RECENT_ACTIONS:]

    def successful_claims(self) -> set[str]:
        """Every claim some earlier, successful action in this session backs."""
        return {c for a in self.recent_actions if a.ok for c in a.claims}

    def drop_past_slots(self, now: datetime) -> None:
        cutoff = now.astimezone(MX_TIMEZONE).strftime("%Y-%m-%dT%H:%M")
        self.offered_slots = [s for s in self.offered_slots if s.slot_id > cutoff]

    def is_empty(self) -> bool:
        return not (
            self.offered_slots or self.known_appointments or self.draft or self.recent_actions
        )

    # ------------------------------------------------------------------
    # Prompt rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Spanish prompt block for the dynamic part of the system prompt."""
        if self.is_empty():
            return ""

        lines = [
            "\n\nESTADO DE LA CONVERSACIÓN (lo registró el sistema al ejecutar las "
            "herramientas; es la fuente de verdad sobre lo que ya pasó — si no coincide con "
            "algo que dijiste antes en el chat, lo correcto es esto):"
        ]

        if self.recent_actions:
            lines.append("Acciones ejecutadas en esta conversación:")
            for a in self.recent_actions:
                outcome = "" if a.ok else " (FALLÓ — no se realizó)"
                lines.append(f"- {a.summary}{outcome}")

        if self.draft:
            lines.append(
                "Cita preparada que espera la aprobación del paciente (todavía NO está "
                f"agendada): {self.draft.summary}"
            )

        if self.known_appointments:
            lines.append("Citas del paciente según la última consulta:")
            for a in self.known_appointments:
                # Patient-supplied text on its way into the prompt.
                who = f" — {sanitize_for_prompt(a.patient_name)}" if a.patient_name else ""
                lines.append(f"- {a.label}{who} — estado: {a.status} (ID {a.id})")

        if self.offered_slots:
            lines.append(
                "Horarios que consultaste (pueden haberse ocupado desde entonces; al "
                "reservar se vuelve a verificar). Usa el slot_id entre corchetes tal cual:"
            )
            by_date: dict[str, list[OfferedSlot]] = {}
            for s in sorted(self.offered_slots, key=lambda s: s.slot_id):
                by_date.setdefault(s.date_label, []).append(s)
            for date_label, slots in by_date.items():
                times = ", ".join(f"{s.time_label} [{s.slot_id}]" for s in slots)
                lines.append(f"- {date_label}: {times}")

        return "\n".join(lines)
