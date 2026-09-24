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

def invariants(r: Result) -> list[str]:
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
        (datetime.strptime(a["start"], "%Y-%m-%dT%H:%M"), a) for a in active
    )
    for (s1, a1), (s2, _) in zip(spans, spans[1:]):
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
        name="double_yes_books_once",
        tags=["duplicates"],
        opening=["Cita para el jueves a las 9 por favor"],
        persona=JUAN + "\nCuando te pidan confirmar, contesta 'sí sí, confírmala' y luego otra vez 'sí'.",
        goal="Agendar el jueves a las 9.",
        check=_check_no_duplicate_booking,
    ),
]
