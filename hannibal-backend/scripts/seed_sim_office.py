#!/usr/bin/env python3
"""Seed the single office the conversation simulator runs against.

The simulator's database is disposable, so it needs a way to come back from
nothing. This builds a practice that behaves like a real one — it goes through
the same `create_office` the dashboard uses, so it gets the default reminder
rules and the statutory holiday blocks exactly as a doctor's practice would. A
simulator seeded by hand-rolled inserts would quietly diverge from production and
stop being evidence of anything.

What it deliberately does differently is the credentials:

    whatsapp_token     = "sim-invalid-token"
    whatsapp_phone_id  = "000000000000000"

That is the safety layer that does not depend on configuration. The real Meta
client takes the phone id and token *per call from this row*, so even if someone
flipped WHATSAPP_TRANSPORT back to "meta" in a simulator environment, the send
would get a 401 from Meta rather than reach a real person.

`google_calendar_id` is left for the operator to point at a throwaway secondary
calendar ("Argos Sim"): every event the simulator creates lands there, and
cleaning up means deleting that calendar rather than picking events out of the
doctor's real one.

Usage:
    python scripts/seed_sim_office.py             # seed, or complain if already seeded
    python scripts/seed_sim_office.py --if-empty  # seed only if empty, never complain
    python scripts/seed_sim_office.py --reset     # wipe and reseed

`--if-empty` is what the container runs at boot: it makes the throwaway database
genuinely throwaway, since destroying it and restarting brings the office back
with no one having to remember a command. It exits 0 when there was nothing to
do, so only a real failure stops the boot — and a simulator with no office is
useless, so failing loudly there is right.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import time
from pathlib import Path
from uuid import uuid4

# Running this as `python scripts/seed_sim_office.py` puts `scripts/` at the
# front of sys.path, not the backend root, so `app` wouldn't import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select

from app.config import settings
from app.db.base import dispose_engine, get_async_session_maker
from app.db.models import (
    Appointment,
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


def _refuse_in_production() -> None:
    """Never let this run against a real database."""
    if settings.is_production:
        raise SystemExit(
            "refusing to run: ENVIRONMENT=production. This script wipes and "
            "reseeds an entire database."
        )
    if not settings.simulation_mode:
        raise SystemExit(
            "refusing to run: SIMULATION_MODE is off. Set it so this cannot be "
            "pointed at a normal environment by accident."
        )


async def _wipe(db) -> None:
    for model in WIPE_ORDER:
        await db.execute(delete(model))
    await db.commit()
    print("  wiped every table")


async def _seed(db) -> Office:
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

    # The credentials that make a real send fail rather than reach anyone.
    office.whatsapp_phone_id = SIM_PHONE_ID
    office.whatsapp_token = SIM_TOKEN
    office.whatsapp_app_active = True

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


async def main(reset: bool, if_empty: bool) -> int:
    _refuse_in_production()

    async with get_async_session_maker()() as db:
        existing = (await db.execute(select(Office))).scalars().all()

        if existing and not reset:
            if if_empty:
                print(f"{len(existing)} office(s) already present — nothing to do.")
                await dispose_engine()
                return 0
            print(
                f"{len(existing)} office(s) already present — pass --reset to wipe "
                "and reseed. Doing nothing."
            )
            return 1

        if existing:
            await _wipe(db)

        office = await _seed(db)

        rules = (
            await db.execute(
                select(ReminderRule).where(ReminderRule.office_id == office.id)
            )
        ).scalars().all()
        blocks = (
            await db.execute(
                select(TimeBlock).where(TimeBlock.office_id == office.id)
            )
        ).scalars().all()

    await dispose_engine()

    print(f"\n  office        {office.name} ({office.id})")
    print(f"  doctor        {OWNER_PHONE}  (+ secretaria {SECONDARY_OWNER_PHONE})")
    print(f"  paciente      {DEFAULT_PATIENT_PHONE}  Juan Pérez")
    print(f"  horarios      lun-vie 9-14 y 16-19, 30 min + 10 de buffer")
    print(f"  recordatorios {len(rules)} reglas por defecto")
    print(f"  festivos      {len(blocks)} bloqueos")
    print(f"  whatsapp      phone_id={SIM_PHONE_ID} token inválido a propósito")
    print(
        "\n  pendiente: apunta office.google_calendar_id a un calendario "
        "secundario desechable"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="wipe every table first (the simulator's database is disposable)",
    )
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="seed only when the database is empty, and exit 0 either way",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.reset, args.if_empty)))
