"""Conversation scenarios for the assistant, with deterministic outcome checks.

Every scenario starts from a freshly reset simulator with the clock on a Monday
at 08:00 (see SimClient.start_on_monday), against the seeded practice:

- Monday to Friday, 9:00-14:00 and 16:00-19:00; closed on weekends.
- First visit: 40 min + 10 min buffer, so the offered grid is
  9:00, 9:50, 10:40, 11:30, 12:20, 13:10, 16:00, 16:50, 17:40.
- Default patient: Juan Pérez (5215550000001), no appointment history.

A check reads the END STATE — the appointments table, the traces — never the
wording of a reply, except where the wording is the product guarantee (not
promising what doesn't exist). A scenario passes when its check returns no
failures and the global invariants hold.

Adding a scenario is adding one Scenario(...) to SCENARIOS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Awaitable, Callable, Optional

DEFAULT_PATIENT = "5215550000001"

# The seeded practice's hours: (weekday Mon=0..Fri=4) -> shifts.
SHIFTS = [(time(9, 0), time(14, 0)), (time(16, 0), time(19, 0))]
FIRST_VISIT_GRID = ["09:00", "09:50", "10:40", "11:30", "12:20", "13:10", "16:00", "16:50", "17:40"]


@dataclass
class Result:
    monday: date
    appointments: list[dict]
    transcript: list[tuple[str, str]]  # (role, text), role: patient|assistant
    traces: list[dict]
    fixtures: dict
    whatsapp_id: str
    # Events in the connected Google Calendar for the scenario's week, or None
    # when the simulator has no calendar (the Google checks are then skipped).
    gcal_events: Optional[list[dict]] = None
    # Every WhatsApp message the office sent during the scenario (all recipients).
    outbox: list[dict] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    urgencies: list[dict] = field(default_factory=list)
    bot_paused: bool = False
    channel: str = "patient"

    def sent_to(self, whatsapp_id: str) -> list[str]:
        """Texts actually delivered to one number (templates rendered as their params)."""
        out = []
        for e in self.outbox:
            if e.get("to") == whatsapp_id:
                out.append(e.get("body") or " ".join(
                    str(p.get("text", p)) for p in (e.get("params") or [])
                ))
        return out

    def manual_blocks(self) -> list[dict]:
        return [b for b in self.blocks if b.get("origin") == "manual"]

    # --- helpers for checks -------------------------------------------------

    def day(self, offset: int) -> date:
        return self.monday + timedelta(days=offset)

    def active(self) -> list[dict]:
        return [a for a in self.appointments if a["status"] in ("scheduled", "confirmed")]

    def active_on(self, offset: int) -> list[dict]:
        d = self.day(offset).isoformat()
        return [a for a in self.active() if a["start"].startswith(d)]

    def replies(self) -> list[str]:
        return [t for r, t in self.transcript if r == "assistant"]

    def tools_called(self) -> list[str]:
        return [c["name"] for t in self.traces for c in (t.get("tool_calls") or [])]


@dataclass
class Scenario:
    name: str
    opening: list  # each item: a message, or a list of messages sent as a burst
    persona: str
    goal: str
    check: Callable[[Result], list[str]]
    setup: Optional[Callable[..., Awaitable[dict]]] = None
    max_turns: int = 8
    whatsapp_id: str = DEFAULT_PATIENT
    tags: list[str] = field(default_factory=list)
    # Needs a Google Calendar connected to the simulator; skipped otherwise.
    requires_gcal: bool = False
    # Who talks to the assistant: "patient", or "doctor" (the owner's number).
    channel: str = "patient"
    # Doctor scenarios that end in a deliberate overbook.
    allows_overlap: bool = False
    # Whether escalating to the doctor is an acceptable outcome here. Everywhere
    # else an urgency request is a failure: it leaves the patient without the
    # appointment they asked for and sends the doctor a false alarm.
    allows_urgency: bool = False


def _hhmm(appt: dict) -> str:
    return appt["start"][11:16]


# Same cut as the availability tool's part_of_day: "tarde" starts at noon.
def _afternoon(appt: dict) -> bool:
    return _hhmm(appt) >= "12:00"


def _morning(appt: dict) -> bool:
    return _hhmm(appt) < "12:00"


def expect(cond: bool, message: str) -> list[str]:
    return [] if cond else [message]


# ---------------------------------------------------------------------------
# Global invariants — checked on every scenario
# ---------------------------------------------------------------------------

def invariants(r: Result, allow_overlap: bool = False) -> list[str]:
    failures = []
    active = r.active()
    for a in active:
        start = datetime.strptime(a["start"], "%Y-%m-%dT%H:%M")
        end = start + timedelta(minutes=a["duration_minutes"] or 30)
        in_hours = start.weekday() < 5 and any(
            start.time() >= s and end.time() <= e for s, e in SHIFTS
        )
        if not in_hours:
            failures.append(f"appointment outside working hours: {a['start']}")
    spans = sorted(
        ((datetime.strptime(a["start"], "%Y-%m-%dT%H:%M"), a) for a in active),
        key=lambda pair: pair[0],
    )
    for (s1, a1), (s2, _) in zip(spans, spans[1:]):
        if allow_overlap:
            break
        if s1 + timedelta(minutes=a1["duration_minutes"] or 30) > s2:
            failures.append(f"overlapping appointments at {a1['start']}")
    for t in r.traces:
        if t.get("outcome") == "error":
            failures.append(f"turn errored: {t.get('error')}")
    if r.gcal_events is not None:
        failures += gcal_invariants(r)
    return failures


def gcal_invariants(r: Result) -> list[str]:
    """The doctor's calendar must say what the appointments table says.

    An active appointment has its event, at its time, blocking the slot. A
    cancelled or moved one no longer blocks it (the app marks it transparent
    rather than deleting it). This is Rule 12 checked from the outside: the
    booking engine swallows Google errors on purpose, so a silent failure
    shows up here, not as an exception.
    """
    failures = []
    by_id = {e["id"]: e for e in r.gcal_events}
    for a in r.appointments:
        event = by_id.get(a.get("google_event_id") or "")
        start = datetime.strptime(a["start"], "%Y-%m-%dT%H:%M")
        end = (start + timedelta(minutes=a["duration_minutes"] or 30)).strftime("%Y-%m-%dT%H:%M")
        if a["status"] in ("scheduled", "confirmed"):
            if event is None:
                failures.append(f"active appointment {a['start']} has no Google Calendar event")
            elif event["start"] != a["start"] or event["end"] != end:
                failures.append(
                    f"calendar event {event['start']}-{event['end']} doesn't match appointment {a['start']}-{end}"
                )
            elif event["transparency"] == "transparent" or event["status"] == "cancelled":
                failures.append(f"active appointment {a['start']} doesn't block its calendar slot")
        elif a["status"] == "cancelled" and event is not None:
            if event["transparency"] != "transparent" and event["status"] != "cancelled":
                failures.append(f"cancelled appointment {a['start']} still blocks the calendar")
    return failures


# ---------------------------------------------------------------------------
# Setups
# ---------------------------------------------------------------------------

async def _block_tuesday(sim, monday: date) -> dict:
    d = (monday + timedelta(days=1)).isoformat()
    await sim.fixture_block(f"{d}T08:00", f"{d}T20:00", "Congreso")
    return {}


async def _block_whole_week(sim, monday: date) -> dict:
    for offset in range(0, 5):  # today (Monday) included: "esta semana" has no room
        d = (monday + timedelta(days=offset)).isoformat()
        await sim.fixture_block(f"{d}T08:00", f"{d}T20:00", "Vacaciones")
    return {}


async def _gcal_meeting_tuesday_morning(sim, monday: date) -> dict:
    d = (monday + timedelta(days=1)).isoformat()
    return {"event": await sim.fixture_gcal_event(f"{d}T10:00", f"{d}T12:00", "Junta hospital")}


async def _gcal_away_tuesday(sim, monday: date) -> dict:
    d = (monday + timedelta(days=1)).isoformat()
    return {"event": await sim.fixture_gcal_event(f"{d}T08:00", f"{d}T20:00", "Congreso")}


async def _appt_today_1130(sim, monday: date) -> dict:
    appt = await sim.fixture_appointment(f"{monday.isoformat()}T11:30", reason="Revisión")
    return {"appt": appt}


async def _appt_wednesday_0900(sim, monday: date) -> dict:
    d = (monday + timedelta(days=2)).isoformat()
    return {"appt": await sim.fixture_appointment(f"{d}T09:00", reason="Dolor de rodilla")}


async def _appt_thursday_0900(sim, monday: date) -> dict:
    d = (monday + timedelta(days=3)).isoformat()
    return {"appt": await sim.fixture_appointment(f"{d}T09:00", reason="Chequeo")}


async def _appt_tomorrow_and_day_before_reminder(sim, monday: date) -> dict:
    d = (monday + timedelta(days=1)).isoformat()
    appt = await sim.fixture_appointment(f"{d}T10:40", reason="Chequeo")
    # Move to Monday 11:00: the day-before reminder (24h ahead) goes out and
    # primes the confirmation context in the patient's session.
    now = await sim.now()
    await sim.advance_to(now.replace(hour=11, minute=0))
    return {"appt": appt}


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

JUAN = """Te llamas Juan Pérez. Tu motivo: dolor de espalda baja desde hace una semana.
No tomas medicamentos. Es tu primera vez en el consultorio."""


def _check_book_tomorrow_4pm(r: Result) -> list[str]:
    tue = r.active_on(1)
    return (
        expect(len(r.active()) == 1, f"expected 1 active appointment, got {len(r.active())}")
        + expect(len(tue) == 1 and _hhmm(tue[0]) == "16:00", "expected Tuesday 16:00 (4 PM)")
    )


def _check_option_two(r: Result) -> list[str]:
    thu = r.active_on(3)
    if len(thu) != 1:
        return [f"expected 1 appointment on Thursday, got {len(thu)}"]
    # The option the patient chose ("la 2") is whatever line 2 of the list said.
    listing = next((t for t in r.replies() if re.search(r"(?m)^\s*\**2[\.\)]", t)), "")
    line = next((l for l in listing.splitlines() if re.match(r"^\s*\**2[\.\)]", l)), "")
    hhmm = _hhmm(thu[0])
    h, m = int(hhmm[:2]), hhmm[3:]
    label = f"{h % 12 or 12}:{m} {'AM' if h < 12 else 'PM'}"
    return expect(label in line, f"booked {label} but option 2 was: {line!r}")


def _check_this_wednesday_morning(r: Result) -> list[str]:
    wed = r.active_on(2)
    return expect(len(wed) == 1 and _morning(wed[0]), "expected this Wednesday, morning")


def _check_friday_near_10(r: Result) -> list[str]:
    fri = r.active_on(4)
    return (
        expect(len(fri) == 1, f"expected 1 appointment on Friday, got {len(fri)}")
        + expect(all(_hhmm(a) in FIRST_VISIT_GRID for a in fri), "booked a time off the offered grid")
        + expect(all(_morning(a) for a in fri), "expected a morning slot near 10")
    )


def _check_next_available(r: Result) -> list[str]:
    return (
        expect(not r.active_on(1), "booked on the blocked Tuesday")
        + expect(len(r.active_on(2)) == 1, "expected the next free day (Wednesday) to be booked")
    )


def _check_burst(r: Result) -> list[str]:
    first_replies = r.fixtures.get("replies_after_burst", 0)
    thu = r.active_on(3)
    return (
        expect(first_replies == 1, f"burst got {first_replies} replies instead of 1")
        + expect(len(thu) == 1 and _afternoon(thu[0]), "expected Thursday afternoon")
    )


def _check_third_party(r: Result) -> list[str]:
    ana = [a for a in r.active() if (a["patient_name"] or "").lower().startswith("ana")]
    return (
        expect(len(ana) == 1, "expected one appointment for Ana López")
        + expect(
            bool(ana) and ana[0]["patient_whatsapp_id"] == "5215512345678",
            "Ana's appointment is not under her own phone",
        )
        + expect(
            not [a for a in r.active() if a["patient_whatsapp_id"] == DEFAULT_PATIENT],
            "an appointment was booked for the writer instead",
        )
    )


def _check_cancel_today(r: Result) -> list[str]:
    appt = next((a for a in r.appointments if a["id"] == r.fixtures["appt"]), None)
    return (
        expect(appt is not None and appt["status"] == "cancelled", "today's appointment was not cancelled")
        + expect(not r.active(), "something else is still booked")
    )


def _check_reschedule(r: Result) -> list[str]:
    old = next((a for a in r.appointments if a["id"] == r.fixtures["appt"]), None)
    thu = r.active_on(3)
    return (
        expect(old is not None and old["status"] == "cancelled", "the Wednesday appointment was not released")
        + expect(len(thu) == 1 and _afternoon(thu[0]), "expected the new appointment Thursday afternoon")
        + expect(len(r.active()) == 1, f"expected exactly 1 active appointment, got {len(r.active())}")
    )


_PROMISE_RE = re.compile(
    r"te (aviso|avisar[ée]|notific|escribo|contacto|mando un mensaje)\b.*(libera|desocupa|espacio|lugar)"
    r"|lista de espera",
    re.IGNORECASE,
)


def _check_no_waitlist_promise(r: Result) -> list[str]:
    promised = [t for t in r.replies() if _PROMISE_RE.search(t)]
    return (
        expect(not promised, f"promised a notification that doesn't exist: {promised[:1]}")
        + expect(not r.active(), "booked despite the whole week being blocked")
    )


def _check_price(r: Result) -> list[str]:
    return (
        expect(any("800" in t for t in r.replies()), "didn't quote the first-visit price ($800)")
        + expect(not r.active(), "booked without being asked to")
    )


def _check_insurance_unknown(r: Result) -> list[str]:
    flat_no = [t for t in r.replies() if re.search(r"\bno (lo |la )?aceptamos\b|\bno se acepta\b", t, re.I)]
    return expect(not flat_no, "flatly denied an insurer that isn't in the list")


def _check_emergency(r: Result) -> list[str]:
    return (
        expect("request_urgent_appointment" in r.tools_called(), "chest pain didn't reach the doctor")
        + expect(not r.active(), "booked a normal appointment for an emergency")
        + expect(
            any(re.search(r"\b911\b|urgencias", t, re.I) for t in r.replies()),
            "never told the patient to call 911 / go to urgencias",
        )
    )


def _check_confirm_attendance(r: Result) -> list[str]:
    appt = next((a for a in r.appointments if a["id"] == r.fixtures["appt"]), None)
    return (
        expect(appt is not None and appt["status"] == "confirmed", "attendance not confirmed")
        + expect(len(r.active()) == 1, "an extra appointment was created")
    )


def _check_informal(r: Result) -> list[str]:
    thu = r.active_on(3)
    return expect(len(thu) == 1 and _afternoon(thu[0]), "expected Thursday afternoon")


def _check_angry_today(r: Result) -> list[str]:
    today = r.active_on(0)
    urgent = "request_urgent_appointment" in r.tools_called()
    return expect(len(today) == 1 or urgent, "neither booked today nor escalated")


def _check_same_day_move(r: Result) -> list[str]:
    thu = r.active_on(3)
    old = next((a for a in r.appointments if a["id"] == r.fixtures["appt"]), None)
    return (
        expect(len(thu) == 1, f"expected one appointment on Thursday, got {len(thu)}")
        + expect(bool(thu) and _afternoon(thu[0]), "expected it moved to the afternoon")
        + expect(old is not None and old["status"] == "cancelled", "the 9:00 one is still active")
    )


def _check_gap_hour(r: Result) -> list[str]:
    tue = r.active_on(1)
    return (
        expect(len(tue) == 1, f"expected 1 appointment on Tuesday, got {len(tue)}")
        + expect(all(_hhmm(a) in FIRST_VISIT_GRID for a in tue), "booked a time outside the grid")
    )


def _check_gcal_meeting_respected(r: Result) -> list[str]:
    tue = r.active_on(1)
    clash = [
        a for a in tue
        if _hhmm(a) < "12:00"
        and (datetime.strptime(a["start"], "%Y-%m-%dT%H:%M")
             + timedelta(minutes=a["duration_minutes"] or 30)).strftime("%H:%M") > "10:00"
    ]
    return (
        expect(len(tue) == 1, f"expected 1 appointment on Tuesday, got {len(tue)}")
        + expect(not clash, f"booked over the doctor's Google meeting (10:00-12:00): {[a['start'] for a in clash]}")
    )


def _check_gcal_away_day(r: Result) -> list[str]:
    return (
        expect(not r.active_on(1), "booked on a day the doctor's Google Calendar is fully busy")
        + expect(len(r.active_on(2)) == 1, "expected the next free day (Wednesday) to be booked")
    )


def _check_proximo_asks_then_next_week(r: Result) -> list[str]:
    # The patient only says which Wednesday when asked, so a booking on the
    # right one means the assistant asked instead of assuming.
    return (
        expect("ambiguous_date" in _tool_result_text(r), "the tool never flagged 'el próximo miércoles' as ambiguous")
        + expect(len(r.active_on(9)) == 1, "expected the Wednesday of NEXT week (the one the patient chose)")
        + expect(not r.active_on(2), "booked this week's Wednesday without asking")
    )


def _check_day_number(r: Result) -> list[str]:
    target = r.day(4)  # the scenario asks for this day by its number
    booked = [a for a in r.active() if a["start"].startswith(target.isoformat())]
    return expect(len(booked) == 1, f"expected an appointment on the {target.day} ({target.isoformat()})")


def _tool_result_text(r: Result) -> str:
    return " ".join(str(c.get("result")) for t in r.traces for c in (t.get("tool_calls") or []))


def _check_no_duplicate_booking(r: Result) -> list[str]:
    return expect(len(r.active()) == 1, f"expected exactly 1 appointment, got {len(r.active())}")


SCENARIOS: list[Scenario] = [
    Scenario(
        name="book_tomorrow_4pm",
        tags=["dates", "12h"],
        opening=["Hola, quiero una cita para mañana a las 4 de la tarde"],
        persona=JUAN,
        goal="Agendar una cita para mañana a las 4 de la tarde.",
        check=_check_book_tomorrow_4pm,
    ),
    Scenario(
        name="pick_option_two",
        tags=["options"],
        opening=["¿Qué horarios tienes el jueves?"],
        persona=JUAN,
        goal="Cuando te dé la lista numerada, elige la opción 2 escribiendo solo 'la 2'. Luego agenda.",
        check=_check_option_two,
    ),
    Scenario(
        name="this_wednesday_morning",
        tags=["dates"],
        opening=["¿Me puedes dar cita el miércoles en la mañana?"],
        persona=JUAN + "\nTe refieres al miércoles de esta semana. Si te dan opciones, elige la primera.",
        goal="Agendar el miércoles de esta semana por la mañana.",
        check=_check_this_wednesday_morning,
    ),
    Scenario(
        name="friday_at_ten_not_on_grid",
        tags=["12h", "grid"],
        opening=["Quiero cita el viernes a las 10"],
        persona=JUAN + "\nSi a las 10 no hay, aceptas el horario más cercano de la mañana.",
        goal="Agendar el viernes por la mañana, lo más cerca de las 10.",
        check=_check_friday_near_10,
    ),
    Scenario(
        name="full_day_offers_next_available",
        tags=["no_slots"],
        setup=_block_tuesday,
        opening=["Hola, necesito cita para mañana"],
        persona=JUAN + "\nSi mañana no se puede, aceptas el primer horario del siguiente día que te ofrezcan.",
        goal="Conseguir una cita lo antes posible.",
        check=_check_next_available,
    ),
    Scenario(
        name="burst_of_messages",
        tags=["burst"],
        opening=[["hola", "quiero agendar una cita", "para el jueves en la tarde"]],
        persona=JUAN + "\nSi te dan opciones, elige la primera.",
        goal="Agendar el jueves por la tarde.",
        check=_check_burst,
    ),
    Scenario(
        name="book_for_girlfriend",
        tags=["third_party"],
        opening=["Hola, quiero sacar una cita para mi novia"],
        persona=(
            "Eres Juan Pérez y la cita NO es para ti: es para tu novia, Ana López. "
            "Su teléfono es 55 1234 5678. Motivo: chequeo general. Es su primera vez. "
            "Quieren el jueves; si te dan opciones, elige la primera."
        ),
        goal="Agendar la cita de Ana López para el jueves.",
        check=_check_third_party,
    ),
    Scenario(
        name="cancel_same_day",
        tags=["cancel"],
        setup=_appt_today_1130,
        opening=["Ya no voy a poder ir hoy a mi cita, cancélala por favor"],
        persona=JUAN + "\nSi te preguntan el motivo: te salió un compromiso de trabajo. No quieres reagendar por ahora.",
        goal="Cancelar tu cita de hoy.",
        check=_check_cancel_today,
    ),
    Scenario(
        name="reschedule_to_thursday_afternoon",
        tags=["reschedule"],
        setup=_appt_wednesday_0900,
        opening=["Necesito cambiar mi cita del miércoles para el jueves en la tarde"],
        persona=JUAN + "\nSi te dan opciones, elige la primera.",
        goal="Mover tu cita del miércoles al jueves por la tarde.",
        check=_check_reschedule,
    ),
    Scenario(
        name="no_waitlist_promises",
        tags=["promises"],
        setup=_block_whole_week,
        opening=["¿Tienes algo esta semana? Si no, ¿me avisas si se libera un espacio?"],
        persona=JUAN + "\nSolo te interesa esta semana. Si no hay, no quieres agendar otra semana.",
        goal="Saber si hay lugar esta semana; si no hay, que te avisen si se libera algo.",
        check=_check_no_waitlist_promise,
        max_turns=4,
    ),
    Scenario(
        name="price_question",
        tags=["info"],
        opening=["Buenas, ¿cuánto cuesta la consulta?"],
        persona=JUAN + "\nSolo quieres saber el precio, no agendar todavía.",
        goal="Saber cuánto cuesta la consulta.",
        check=_check_price,
        max_turns=3,
    ),
    Scenario(
        name="insurer_not_in_list",
        tags=["info"],
        opening=["¿Aceptan Seguros Monterrey?"],
        persona=JUAN + "\nSolo quieres saber si aceptan tu seguro.",
        goal="Saber si aceptan Seguros Monterrey.",
        check=_check_insurance_unknown,
        max_turns=3,
    ),
    Scenario(
        name="chest_pain_escalates",
        tags=["urgency"],
        opening=["Tengo un dolor de pecho muy fuerte desde hace una hora, necesito ver al doctor"],
        persona=JUAN + "\nSí es una emergencia. El dolor empezó hace una hora y se va al brazo izquierdo.",
        goal="Que el doctor sepa de tu urgencia.",
        check=_check_emergency,
        allows_urgency=True,
        max_turns=4,
    ),
    Scenario(
        name="confirm_after_reminder",
        tags=["confirmation"],
        setup=_appt_tomorrow_and_day_before_reminder,
        opening=["Sí, ahí estaré"],
        persona=JUAN,
        goal="Confirmar que vas a ir a tu cita de mañana.",
        check=_check_confirm_attendance,
        max_turns=3,
    ),
    Scenario(
        name="informal_typos",
        tags=["language"],
        opening=["kiero sita pa el juebes x la tarde xfa"],
        persona=JUAN + "\nEscribes informal. Si te dan opciones, elige la primera.",
        goal="Agendar el jueves por la tarde.",
        check=_check_informal,
    ),
    Scenario(
        name="angry_patient_wants_today",
        tags=["tone"],
        opening=["Llevo días escribiendo y nadie contesta, pésimo servicio. Necesito cita HOY"],
        persona=JUAN + "\nEstás molesto pero aceptas el primer horario de hoy que te den. No es una emergencia.",
        goal="Conseguir cita hoy.",
        check=_check_angry_today,
        allows_urgency=True,
    ),
    Scenario(
        name="second_same_day_becomes_move",
        tags=["same_day"],
        setup=_appt_thursday_0900,
        opening=["Quiero una cita el jueves a las 5 de la tarde"],
        persona=JUAN + "\nSi te dicen que ya tienes cita ese día, prefieres mover la que tienes a la tarde (la más cercana a las 5).",
        goal="Tener tu cita del jueves en la tarde en lugar de en la mañana.",
        check=_check_same_day_move,
    ),
    Scenario(
        name="hour_in_the_lunch_gap",
        tags=["grid", "no_slots"],
        opening=["¿Tienes a las 3 de la tarde el martes?"],
        persona=JUAN + "\nSi a las 3 no hay, aceptas el primer horario que te ofrezcan ese martes.",
        goal="Agendar el martes.",
        check=_check_gap_hour,
    ),
    Scenario(
        name="gcal_personal_meeting_blocks_slots",
        tags=["gcal", "no_slots"],
        requires_gcal=True,
        setup=_gcal_meeting_tuesday_morning,
        opening=["¿Tienes el martes a las 10:40?"],
        persona=JUAN + "\nSi a las 10:40 no se puede, aceptas el primer horario que te ofrezcan ese martes.",
        goal="Agendar el martes.",
        check=_check_gcal_meeting_respected,
    ),
    Scenario(
        name="gcal_doctor_away_offers_next_day",
        tags=["gcal", "no_slots"],
        requires_gcal=True,
        setup=_gcal_away_tuesday,
        opening=["Hola, necesito cita para mañana"],
        persona=JUAN + "\nSi mañana no se puede, aceptas el primer horario del siguiente día que te ofrezcan.",
        goal="Conseguir una cita lo antes posible.",
        check=_check_gcal_away_day,
    ),
    Scenario(
        name="proximo_miercoles_is_asked",
        tags=["dates", "ambiguity"],
        opening=["¿Tienes cita el próximo miércoles?"],
        persona=JUAN + "\nSi te preguntan cuál miércoles, es el de la semana que entra (no el de esta semana). Si te dan opciones de hora, elige la primera.",
        goal="Agendar el miércoles de la semana que entra.",
        check=_check_proximo_asks_then_next_week,
    ),
    Scenario(
        name="day_by_number",
        tags=["dates"],
        # Friday of the scenario's week, named only by its day number.
        opening=[lambda monday: f"Quiero cita el día {(monday + timedelta(days=4)).day} en la mañana"],
        persona=JUAN + "\nSi te dan opciones, elige la primera.",
        goal="Agendar ese día por la mañana.",
        check=_check_day_number,
    ),
    Scenario(
        name="double_yes_books_once",
        tags=["duplicates"],
        opening=["Cita para el jueves a las 9 por favor"],
        persona=JUAN + "\nCuando te pidan confirmar, contesta 'sí sí, confírmala' y luego otra vez 'sí'.",
        goal="Agendar el jueves a las 9.",
        check=_check_no_duplicate_booking,
    ),
]


# ---------------------------------------------------------------------------
# Doctor channel
# ---------------------------------------------------------------------------
#
# The doctor writes from the office's owner number. The simulated doctor gives
# one instruction and answers whatever the assistant asks (approve a draft,
# confirm an overbook). Checks read what actually changed — appointments,
# blocks, urgencies, the pause — and what actually went out to patients.

ANA = "5215550000002"
DOCTOR = "Eres la doctora Elena Ruiz, médico general. Tu consultorio atiende de lunes a viernes."


def _day_iso(monday: date, offset: int) -> str:
    return (monday + timedelta(days=offset)).isoformat()


async def _doc_today_two(sim, monday: date) -> dict:
    d = _day_iso(monday, 0)
    return {
        "juan": await sim.fixture_appointment(f"{d}T11:30", reason="Dolor de espalda"),
        "ana": await sim.fixture_appointment(f"{d}T16:00", patient_whatsapp_id=ANA, patient_name="Ana López", reason="Chequeo"),
    }


async def _doc_juan_tomorrow(sim, monday: date) -> dict:
    return {"juan": await sim.fixture_appointment(f"{_day_iso(monday, 1)}T10:40", reason="Dolor de espalda")}


async def _doc_juan_tomorrow_9(sim, monday: date) -> dict:
    return {"juan": await sim.fixture_appointment(f"{_day_iso(monday, 1)}T09:00", reason="Revisión")}


async def _doc_thursday_two(sim, monday: date) -> dict:
    d = _day_iso(monday, 3)
    return {
        "juan": await sim.fixture_appointment(f"{d}T09:00", reason="Dolor de espalda"),
        "ana": await sim.fixture_appointment(f"{d}T09:50", patient_whatsapp_id=ANA, patient_name="Ana López", reason="Chequeo"),
    }


async def _doc_juan_wednesday_9(sim, monday: date) -> dict:
    return {"juan": await sim.fixture_appointment(f"{_day_iso(monday, 2)}T09:00", reason="Dolor de espalda")}


async def _doc_pending_urgency(sim, monday: date) -> dict:
    return {"urgency": await sim.fixture_urgency(reason="Dolor abdominal fuerte desde la mañana")}


def _by_id(r: Result, appt_id: str) -> Optional[dict]:
    return next((a for a in r.appointments if a["id"] == appt_id), None)


def _active_for(r: Result, whatsapp_id: str) -> list[dict]:
    return [a for a in r.active() if a["patient_whatsapp_id"] == whatsapp_id]


def _check_doc_agenda(r: Result) -> list[str]:
    text = " ".join(r.replies())
    return (
        expect("get_appointments_by_date" in r.tools_called(), "answered without looking at the agenda")
        + expect("Juan" in text and "Ana" in text, "didn't list both patients")
        + expect("11:30" in text and ("4:00 PM" in text or "4:00 p" in text.lower()), "wrong or missing times")
        + expect(len(r.active()) == 2, "the agenda changed while only being read")
    )


def _check_doc_empty_saturday(r: Result) -> list[str]:
    invented = [t for t in r.replies() if re.search(r"\b\d{1,2}:\d{2}\b", t)]
    return (
        expect(not r.active(), "something got booked")
        + expect(not invented, f"quoted times for an empty day: {invented[:1]}")
    )


def _check_doc_cancel_notice(r: Result) -> list[str]:
    appt = _by_id(r, r.fixtures["juan"])
    notices = r.sent_to(DEFAULT_PATIENT)
    return (
        expect(appt is not None and appt["status"] == "cancelled", "the appointment wasn't cancelled")
        + expect(len(notices) >= 1, "the patient was never told")
        + expect("confirm_send_messages" in r.tools_called(), "the notice went out without the approve step")
    )


def _check_doc_batch_move(r: Result) -> list[str]:
    failures = []
    for key, wid in (("juan", DEFAULT_PATIENT), ("ana", ANA)):
        old = _by_id(r, r.fixtures[key])
        moved = [a for a in _active_for(r, wid) if a["start"].startswith(r.day(4).isoformat()) and _afternoon(a)]
        failures += expect(old is not None and old["status"] == "cancelled", f"{key}'s Thursday cita is still active")
        failures += expect(len(moved) == 1, f"{key} wasn't moved to Friday afternoon")
        failures += expect(bool(r.sent_to(wid)), f"{key} wasn't notified")
    return failures


def _check_doc_block(r: Result) -> list[str]:
    tue = r.day(1).isoformat()
    covering = [
        b for b in r.manual_blocks()
        if b["start"] <= f"{tue}T16:00" and b["end"] >= f"{tue}T19:00"
    ]
    too_wide = [b for b in covering if b["start"] < f"{tue}T15:00" or b["end"] > f"{tue}T19:30"]
    return (
        expect(len(covering) == 1, f"expected one block covering Tuesday 4-7 PM, got {r.manual_blocks()}")
        + expect(not too_wide, "blocked much more than 4-7 PM")
    )


def _check_doc_new_patient(r: Result) -> list[str]:
    maria = [a for a in r.active() if (a["patient_name"] or "").startswith("María")]
    return (
        expect(len(maria) == 1, "María López's appointment wasn't created")
        + expect(bool(maria) and maria[0]["start"] == f"{r.day(2).isoformat()}T11:30", "wrong day/time for María")
        + expect(bool(maria) and maria[0]["patient_whatsapp_id"] == "5215512345678", "María registered under the wrong phone")
    )


def _check_doc_overbook(r: Result) -> list[str]:
    wed9 = f"{r.day(2).isoformat()}T09:00"
    pedro = [a for a in r.active() if (a["patient_name"] or "").startswith("Pedro") and a["start"] == wed9]
    juan = _by_id(r, r.fixtures["juan"])
    creates = [c for t in r.traces for c in (t.get("tool_calls") or []) if c["name"] == "create_appointment"]
    asked_first = any("error" in str(c.get("result")) for c in creates)
    return (
        expect(len(pedro) == 1, "Pedro wasn't booked at 9:00")
        + expect(juan is not None and juan["status"] == "scheduled", "Juan's cita was touched")
        + expect(asked_first, "overbooked without surfacing the conflict first")
    )


def _check_doc_urgency(r: Result) -> list[str]:
    urgency = next((u for u in r.urgencies if u["id"] == r.fixtures["urgency"]), None)
    today12 = f"{r.day(0).isoformat()}T12:00"
    booked = [a for a in _active_for(r, DEFAULT_PATIENT) if a["start"] == today12]
    return (
        expect(urgency is not None and urgency["status"] == "approved", "the urgency wasn't approved")
        + expect(len(booked) == 1, "no urgent appointment today at 12:00")
        + expect(bool(r.sent_to(DEFAULT_PATIENT)), "the patient wasn't told")
    )


def _check_doc_message_edit(r: Result) -> list[str]:
    sent = r.sent_to(DEFAULT_PATIENT)
    return (
        expect(len(sent) == 1, f"expected exactly one message to Juan, got {len(sent)}")
        + expect(bool(sent) and "estudio" in sent[0].lower(), "the message lost the studies request")
        + expect(bool(sent) and re.search(r"10 min", sent[0].lower()), "the doctor's edit didn't make it in")
    )


def _check_doc_pause(r: Result) -> list[str]:
    return expect(r.bot_paused, "the bot isn't paused")


SCENARIOS += [
    Scenario(
        name="doc_agenda_today", channel="doctor", tags=["doctor", "read"],
        setup=_doc_today_two,
        opening=["¿Qué citas tengo hoy?"],
        persona=DOCTOR, goal="Saber qué citas tienes hoy.",
        check=_check_doc_agenda, max_turns=2,
    ),
    Scenario(
        name="doc_empty_saturday_no_invention", channel="doctor", tags=["doctor", "read"],
        opening=["¿Qué tengo el sábado?"],
        persona=DOCTOR, goal="Saber si tienes citas el sábado.",
        check=_check_doc_empty_saturday, max_turns=2,
    ),
    Scenario(
        name="doc_cancel_with_notice", channel="doctor", tags=["doctor", "cancel"],
        setup=_doc_juan_tomorrow,
        opening=["Cancela la cita de Juan Pérez de mañana, tengo una emergencia familiar"],
        persona=DOCTOR + "\nSi te muestran un aviso para el paciente, apruébalo tal cual.",
        goal="Que la cita quede cancelada y Juan avisado.",
        check=_check_doc_cancel_notice,
    ),
    Scenario(
        name="doc_batch_reschedule", channel="doctor", tags=["doctor", "reschedule", "batch"],
        setup=_doc_thursday_two,
        opening=["Pasa las dos citas del jueves en la mañana al viernes en la tarde"],
        persona=DOCTOR + "\nCualquier horario de la tarde del viernes te sirve. Aprueba los avisos a los pacientes.",
        goal="Que Juan y Ana queden el viernes en la tarde y sepan del cambio.",
        check=_check_doc_batch_move,
    ),
    Scenario(
        name="doc_block_afternoon", channel="doctor", tags=["doctor", "block"],
        opening=["Bloquea el martes de 4 a 7 de la tarde, tengo junta en el hospital"],
        persona=DOCTOR, goal="Que el martes de 4 a 7 PM nadie pueda agendar.",
        check=_check_doc_block,
    ),
    Scenario(
        name="doc_create_new_patient", channel="doctor", tags=["doctor", "book"],
        opening=["Agéndame a María López el miércoles a las 11:30, es primera vez, su cel es 55 1234 5678, motivo revisión general"],
        persona=DOCTOR, goal="Que María quede agendada el miércoles a las 11:30.",
        check=_check_doc_new_patient,
    ),
    Scenario(
        name="doc_overbook_after_confirming", channel="doctor", tags=["doctor", "book", "overbook"],
        allows_overlap=True,
        setup=_doc_juan_wednesday_9,
        opening=["Agenda a Pedro Ramírez el miércoles a las 9, cel 55 8765 4321, motivo dolor de rodilla"],
        persona=DOCTOR + "\nSi te dicen que a esa hora ya hay alguien, contesta que sí, que lo encimes.",
        goal="Que Pedro quede el miércoles a las 9 aunque haya otra cita.",
        check=_check_doc_overbook,
    ),
    Scenario(
        name="doc_approve_urgency", channel="doctor", tags=["doctor", "urgency"],
        setup=_doc_pending_urgency,
        opening=["¿Tengo algo pendiente?"],
        persona=DOCTOR + "\nSi hay una urgencia de Juan Pérez, apruébala para hoy a las 12:00.",
        goal="Resolver lo pendiente.",
        check=_check_doc_urgency,
    ),
    Scenario(
        name="doc_message_with_edit", channel="doctor", tags=["doctor", "messages"],
        setup=_doc_juan_tomorrow_9,
        opening=["Dile a Juan Pérez que traiga sus estudios de sangre a la cita"],
        persona=DOCTOR + "\nCuando te muestre el borrador, pide que también le diga que llegue 10 minutos antes. Luego apruébalo.",
        goal="Que Juan reciba un solo mensaje con ambas indicaciones.",
        check=_check_doc_message_edit,
    ),
    Scenario(
        name="doc_pause_bot", channel="doctor", tags=["doctor", "pause"],
        opening=["Pausa el bot una hora, voy a contestar yo"],
        persona=DOCTOR, goal="Que el bot deje de contestar a los pacientes por una hora.",
        check=_check_doc_pause, max_turns=2,
    ),
]
