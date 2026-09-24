"""Building (and destroying) the practice the simulator runs against.

Lives here rather than in the script so that both callers share it: the CLI, and
the reset endpoint. Resetting a scenario is the simulator's normal way of
starting over — the clock only moves forward, so there is no rewinding — and
having to reach a shell for that would make it a chore instead of a button.

The office is built by the same `create_office` the dashboard calls, so it gets
the default reminder rules and the statutory holiday blocks exactly as a real
practice does. A simulator seeded by hand-rolled inserts would quietly diverge
from production and stop being evidence of anything.

Its Meta credentials are deliberately invalid. The real client reads the phone id
and token *per call from the office row*, so even with the transport flipped back
to "meta" a send gets a 401 rather than reaching a person. That is the layer that
does not depend on anyone configuring anything correctly.
"""

from __future__ import annotations

from datetime import time
from typing import Optional
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    AiTurnTrace,
    AvailabilitySchedule,
    Conversation,
    GoogleCalendarEvent,
    Message,
    Office,
    Patient,
    ReminderRule,
    TimeBlock,
    UrgencyRequest,
)

# Fake numbers, in the shape WhatsApp actually delivers (52 + 1 + 10 digits).
OWNER_PHONE = "5215559876543"
SECONDARY_OWNER_PHONE = "5215559876544"
DEFAULT_PATIENT_PHONE = "5215550000001"

# Credentials that cannot reach anyone. See the module docstring.
SIM_PHONE_ID = "000000000000000"
SIM_TOKEN = "sim-invalid-token"

# Monday to Friday, 9:00-14:00 and 16:00-19:00. Two blocks per day so the
# availability engine has a gap to reason about rather than one flat run.
WEEKDAY_SHIFTS = [(time(9, 0), time(14, 0)), (time(16, 0), time(19, 0))]
WEEKDAYS = [1, 2, 3, 4, 5]  # 0=Sun in this model

# Deleted newest-dependency-first so foreign keys never block the wipe.
WIPE_ORDER = [
    AiTurnTrace,
    Message,
    Conversation,
    GoogleCalendarEvent,
    UrgencyRequest,
    Appointment,
    TimeBlock,
    AvailabilitySchedule,
    ReminderRule,
    Patient,
    Office,
]


async def wipe_all(db: AsyncSession) -> None:
    """Empty every table. Only ever called against a simulator database."""
    for model in WIPE_ORDER:
        await db.execute(delete(model))
    await db.commit()


async def seed_office(db: AsyncSession) -> Office:
    """Create the simulator's single practice, schedules and default patient."""
    from app.modules.offices.schemas import CreateOfficeRequest
    from app.modules.offices.service import create_office

    office = await create_office(
        CreateOfficeRequest(
            name="Consultorio Demo",
            doctor_first_name="Elena",
            doctor_last_name="Ruiz",
            specialty="Medicina general",
            whatsapp_phone=OWNER_PHONE,
            owner_phone=OWNER_PHONE,
            secondary_owner_phone=SECONDARY_OWNER_PHONE,
            city="Ciudad de México",
            state="CDMX",
        ),
        user_id=uuid4(),
        db=db,
    )

    office.whatsapp_phone_id = SIM_PHONE_ID
    office.whatsapp_token = SIM_TOKEN
    office.whatsapp_app_active = True

    # The onboarding answers. Without these the assistant knows nothing about
    # what the practice offers, charges, accepts or treats as urgent — it would
    # say "no tengo esa información" to most of what a patient actually asks,
    # and whole behaviours (urgency triage, intake questions, quoting a price)
    # would never be exercised. Comparing two models against a half-empty
    # practice would not be evidence of much.
    #
    # Drawn from app/core/catalogs.py, the same source onboarding seeds from, so
    # this practice looks like one a doctor actually filled in.
    office.address = "Av. Insurgentes Sur 1234, Del Valle"
    office.assistant_name = "Sofía"
    office.assistant_tone = "cercano"
    office.assistant_gender = "femenino"
    office.welcome_message = (
        "¡Hola! Soy Sofía, asistente del Consultorio Demo. "
        "Con gusto le ayudo a agendar su cita."
    )
    office.services = [
        {"name": "Consulta general", "price": "$800"},
        {"name": "Consulta de seguimiento", "price": "$600"},
        {"name": "Certificado médico", "price": "$400"},
        {"name": "Aplicación de vacunas", "price": "$350"},
    ]
    # "si" | "algunos" | "no" — a string, not a boolean (String(20) column).
    office.accepts_insurance = "algunos"
    office.insurances = ["gnp", "axa", "metlife"]
    office.emergency_symptoms = [
        "Dolor de pecho",
        "Dificultad para respirar",
        "Sangrado que no se detiene",
        "Pérdida de conciencia",
        "Fiebre muy alta que no cede",
    ]
    office.intake_questions = {
        "preset": ["motivo", "desde_cuando", "medicamentos"],
        "custom": "¿Es la primera vez que nos visita?",
    }
    office.new_patient_cost = "$800"
    office.returning_patient_cost = "$600"
    office.new_patient_duration_min = 40
    office.returning_patient_duration_min = 30

    for day in WEEKDAYS:
        for start, end in WEEKDAY_SHIFTS:
            db.add(
                AvailabilitySchedule(
                    office_id=office.id,
                    day_of_week=day,
                    start_time=start,
                    end_time=end,
                    appointment_duration_min=30,
                    buffer_minutes=10,
                    is_active=True,
                )
            )

    db.add(
        Patient(
            office_id=office.id,
            whatsapp_id=DEFAULT_PATIENT_PHONE,
            name="Juan Pérez",
            phone=DEFAULT_PATIENT_PHONE,
        )
    )

    await db.commit()
    await db.refresh(office)
    return office


async def existing_offices(db: AsyncSession) -> list[Office]:
    return list((await db.execute(select(Office))).scalars().all())


# Carried across a reset. The calendar connection is configuration of the
# environment, not part of the scenario: losing it would mean granting Google
# consent again every single time you start over, which would make resetting
# something to avoid rather than the normal way to begin.
CARRIED_OVER = (
    "google_calendar_token",
    "google_calendar_id",
    "google_watch_channel_id",
    "google_watch_resource_id",
    "google_watch_expiry",
    "google_sync_token",
)


async def reset(db: AsyncSession) -> Office:
    """Throw the scenario away and build a fresh one, keeping the calendar link."""
    previous = await existing_offices(db)
    carried = (
        {field: getattr(previous[0], field) for field in CARRIED_OVER}
        if previous
        else {}
    )

    await wipe_all(db)
    office = await seed_office(db)

    if any(v is not None for v in carried.values()):
        for field, value in carried.items():
            setattr(office, field, value)
        await db.commit()
        await db.refresh(office)

    return office


async def ensure_seeded(db: AsyncSession) -> tuple[Office, bool]:
    """Seed only if the database is empty.

    Returns:
        The office, and whether this call created it.
    """
    offices = await existing_offices(db)
    if offices:
        return offices[0], False

    return await seed_office(db), True


def summary(office: Office, rules: int, blocks: int) -> str:
    """The human-readable recap both callers print."""
    return "\n".join(
        [
            f"  office        {office.name} ({office.id})",
            f"  doctor        {OWNER_PHONE}  (+ secretaria {SECONDARY_OWNER_PHONE})",
            f"  paciente      {DEFAULT_PATIENT_PHONE}  Juan Pérez",
            "  horarios      lun-vie 9-14 y 16-19, 30 min + 10 de buffer",
            f"  recordatorios {rules} reglas por defecto",
            f"  festivos      {blocks} bloqueos",
            f"  whatsapp      phone_id={SIM_PHONE_ID} token inválido a propósito",
        ]
    )
