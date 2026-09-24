"""The simulator's operator API.

Everything here is behind Basic auth, and the package it lives in refuses to
import in production (see `app/modules/sim/__init__.py`).

On the inbound path, note what this does *not* do: it does not skip the webhook's
HMAC check. It enters the pipeline one step *after* that check, at
`_process_webhook_async` — the same function the real webhook hands off to once a
signature has been verified. So no code path anywhere accepts an unsigned
webhook; the simulator simply starts from where a verified one would have landed.

It also awaits that processing rather than backgrounding it, which the real
webhook cannot do (Meta requires an immediate 200). That is what lets the UI show
the assistant's reply as the response to the message you just sent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_selection import clear_ai_override, current_selection, set_ai_override
from app.config import settings
from app.core.dependencies import get_db, get_redis
from app.db.models import Office
from app.modules.sim.auth import require_sim_auth
from app.modules.sim import gcal as sim_gcal
from app.modules.sim import seed as sim_seed
from app.modules.sim.runner import (
    CLOCK_KEY,
    advance_clock,
    advance_to_next_event,
    get_offset,
    load_offset_into_context,
    next_event_at,
)
from app.modules.whatsapp.fake_client import OUTBOX_KEY
from app.modules.whatsapp.router import _process_webhook_async
from app.utils.dates import now_mx
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(require_sim_auth)])

STATIC_DIR = Path(__file__).parent / "static"


@router.get("/", include_in_schema=False)
async def sim_ui() -> FileResponse:
    """The simulator itself. Served from the backend so there is one URL,
    one password and no separate frontend deploy to keep in step."""
    return FileResponse(STATIC_DIR / "index.html")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

async def _the_office(db: AsyncSession) -> Office:
    """The simulator's single office.

    A simulator environment holds exactly one seeded office, so resolving it
    needs no id from the caller. Anything else is a broken environment and says
    so rather than picking one arbitrarily.
    """
    offices = (await db.execute(select(Office))).scalars().all()

    if len(offices) == 1:
        return offices[0]

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"the simulator expects exactly one office, found {len(offices)} — "
            "run scripts/seed_sim_office.py against a clean database"
        ),
    )


def _meta_shaped_payload(office: Office, sender: str, text: str) -> dict[str, Any]:
    """Build the webhook body Meta would have delivered for this message."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "sim-entry",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": office.whatsapp_phone_id or "sim",
                                "phone_number_id": office.whatsapp_phone_id,
                            },
                            "contacts": [
                                {"profile": {"name": "Simulador"}, "wa_id": sender}
                            ],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": f"wamid.sim.in.{uuid4().hex}",
                                    "timestamp": str(int(now_mx().timestamp())),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


async def _read_outbox(
    redis_client: aioredis.Redis, office: Office, since: int = 0
) -> list[dict]:
    """Outbound messages recorded for this office, from `since` onwards."""
    key = OUTBOX_KEY.format(phone_number_id=office.whatsapp_phone_id)
    raw = await redis_client.lrange(key, since, -1)
    return [json.loads(item) for item in raw]


async def _outbox_length(redis_client: aioredis.Redis, office: Office) -> int:
    key = OUTBOX_KEY.format(phone_number_id=office.whatsapp_phone_id)
    return await redis_client.llen(key)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class InboundRequest(BaseModel):
    """A message typed into one of the simulator's two panels."""

    sender: Literal["patient", "doctor"]
    text: str = Field(min_length=1, max_length=4000)
    # Which patient is speaking. Omitted means the doctor, or the default patient.
    whatsapp_id: Optional[str] = None
    # Answer this turn with a specific model instead of the configured one. This
    # is the whole point of the simulator for model comparison: the same scenario
    # run twice, once per model, with no redeploy in between.
    provider: Optional[Literal["openai", "anthropic"]] = None
    model: Optional[str] = None
    # How hard a reasoning-first model should think. Changes the answer as
    # much as the model does, so it is part of what a comparison varies.
    reasoning_effort: Optional[
        Literal["none", "minimal", "low", "medium", "high"]
    ] = None


class ClockRequest(BaseModel):
    """How far to move the clock. Either a duration or the next pending event."""

    seconds: Optional[int] = Field(default=None, gt=0)
    to: Optional[Literal["next_event"]] = None


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.get("/state")
async def sim_state(
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Everything the UI needs to render: the clock, the next event, the outbox."""
    office = await _the_office(db)
    await load_offset_into_context()

    upcoming = await next_event_at(office.id)

    return {
        "office": {
            "id": str(office.id),
            "name": office.name,
            "owner_phone": office.owner_phone,
            "secondary_owner_phone": office.secondary_owner_phone,
        },
        "clock": {
            "now": now_mx().isoformat(),
            "offset_seconds": await get_offset(),
        },
        "ai": {
            "configured_provider": current_selection().provider,
            "configured_model": current_selection().model,
            "configured_reasoning_effort": current_selection().reasoning_effort,
        },
        "next_event_at": upcoming.isoformat() if upcoming else None,
        "outbox": await _read_outbox(redis_client, office),
    }


@router.post("/inbound")
async def sim_inbound(
    body: InboundRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Deliver a message as if it had arrived from WhatsApp, and await the reply.

    Returns only the messages produced by *this* turn, so the UI can append them
    rather than re-rendering the whole transcript.
    """
    office = await _the_office(db)
    await load_offset_into_context()

    if body.sender == "doctor":
        sender = office.owner_phone
        if not sender:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="the seeded office has no owner_phone",
            )
    else:
        sender = body.whatsapp_id or "5215550000001"

    if body.model:
        try:
            set_ai_override(
                body.provider or "openai", body.model, body.reasoning_effort
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
            ) from e

    before = await _outbox_length(redis_client, office)
    answered_with = current_selection()

    try:
        await _process_webhook_async(
            _meta_shaped_payload(office, sender, body.text),
            redis_client,
        )
    finally:
        # The override is per turn: leaving it set would silently colour the next
        # message, which is exactly the confusion a comparison must not have.
        clear_ai_override()

    return {
        "sent_as": sender,
        "answered_with": {
            "provider": answered_with.provider,
            "model": answered_with.model,
            "reasoning_effort": answered_with.reasoning_effort,
        },
        "produced": await _read_outbox(redis_client, office, since=before),
    }


@router.post("/clock")
async def sim_clock(
    body: ClockRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Move the clock forward and report everything the move set off."""
    office = await _the_office(db)
    await load_offset_into_context()

    if body.to == "next_event":
        return await advance_to_next_event(office.id)

    if body.seconds is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail='pass either "seconds" or "to": "next_event"',
        )

    try:
        return await advance_clock(office.id, body.seconds)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e


@router.post("/session/reset")
async def sim_reset_session(
    whatsapp_id: str,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Forget one conversation without touching the patient or their appointments.

    This is "the same patient writes again a week later": the bot has no memory
    of the chat but still knows who they are and what they have booked.
    """
    office = await _the_office(db)
    deleted = await redis_client.delete(f"session:{whatsapp_id}:{office.id}")

    logger.info("sim_session_reset", whatsapp_id=whatsapp_id, deleted=bool(deleted))
    return {"whatsapp_id": whatsapp_id, "deleted": bool(deleted)}


@router.post("/outbox/clear")
async def sim_clear_outbox(
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Empty the transcript without resetting anything else."""
    office = await _the_office(db)
    key = OUTBOX_KEY.format(phone_number_id=office.whatsapp_phone_id)
    cleared = await redis_client.llen(key)
    await redis_client.delete(key)
    return {"cleared": cleared}


@router.post("/reset")
async def sim_reset(
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Throw the whole scenario away and start over.

    This is the simulator's only way back: the clock moves forward and never
    rewinds, because Google Calendar cannot rewind with it. So starting a new
    scenario means a new database, a clock at zero and an empty transcript —
    everything this does.

    Destructive by design and by name. It is safe only because the database is
    disposable, which is the whole premise of the environment; the package it
    lives in refuses to load anywhere else.
    """
    # Google doesn't reset with the database: delete the events this scenario
    # created first, or their busy periods haunt the next run (see sim/gcal.py).
    previous = (await db.execute(select(Office))).scalars().first()
    gcal_cleanup = (
        await sim_gcal.delete_simulator_events(db, redis_client, previous)
        if previous is not None
        else {"deleted": 0}
    )

    office = await sim_seed.reset(db)

    await redis_client.delete(CLOCK_KEY)
    await redis_client.delete(OUTBOX_KEY.format(phone_number_id=office.whatsapp_phone_id))

    # Sessions and locks would otherwise outlive the office they belonged to.
    for pattern in (f"session:*:{office.id}", f"avail_cache:{office.id}:*",
                    f"slot_lock:{office.id}:*", f"conv_lock:{office.id}:*",
                    f"inbox:{office.id}:*", f"doctor_state:{office.id}",
                    f"doctor_session:{office.id}"):
        keys = [k async for k in redis_client.scan_iter(match=pattern, count=500)]
        if keys:
            await redis_client.delete(*keys)

    logger.warning("sim_reset", office_id=str(office.id))

    return {
        "office_id": str(office.id),
        "name": office.name,
        "clock": "reset to real time",
        "outbox": "cleared",
        "google_calendar": gcal_cleanup,
    }


@router.get("/appointments")
async def sim_appointments(db: AsyncSession = Depends(get_db)) -> dict:
    """Every appointment in the simulator, for scenario assertions (tests/evals).

    Times are Mexico City wall time, the form a scenario is written in.
    """
    from app.db.models import Appointment, Patient
    from app.core.constants import MX_TIMEZONE

    office = await _the_office(db)
    rows = (await db.execute(
        select(Appointment, Patient)
        .join(Patient, Patient.id == Appointment.patient_id, isouter=True)
        .where(Appointment.office_id == office.id)
        .order_by(Appointment.created_at)
    )).all()
    return {
        "appointments": [
            {
                "id": str(a.id),
                "start": a.start_datetime.astimezone(MX_TIMEZONE).strftime("%Y-%m-%dT%H:%M"),
                "duration_minutes": a.duration_minutes,
                "status": a.status,
                "type": a.type,
                "reason": a.consultation_reason,
                "patient_name": p.name if p else None,
                "patient_whatsapp_id": p.whatsapp_id if p else None,
                "booked_by_patient_id": str(a.booked_by_patient_id) if a.booked_by_patient_id else None,
                "google_event_id": a.google_event_id,
                "arrival_status": a.arrival_status,
            }
            for a, p in rows
        ]
    }


class FixtureAppointment(BaseModel):
    """An appointment a scenario needs to exist before it starts."""

    start: str  # "YYYY-MM-DDTHH:MM", Mexico City time
    patient_whatsapp_id: str = "5215550000001"
    patient_name: str = "Juan Pérez"
    reason: str = "Consulta"
    duration_minutes: int = 30
    status: Literal["scheduled", "confirmed"] = "scheduled"


class FixtureBlock(BaseModel):
    """A time block a scenario needs (e.g. to make a day full)."""

    start: str  # "YYYY-MM-DDTHH:MM"
    end: str
    reason: str = "Bloqueo de prueba"


@router.post("/fixtures/appointment")
async def sim_fixture_appointment(
    body: FixtureAppointment,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Create a scenario precondition through the one real booking path."""
    from datetime import datetime as dt_cls

    from app.core.constants import MX_TIMEZONE
    from app.db.models import Patient
    from app.modules.scheduling.booking import book_appointment

    office = await _the_office(db)
    await load_offset_into_context()
    patient = (await db.execute(
        select(Patient).where(
            (Patient.office_id == office.id)
            & (Patient.whatsapp_id == body.patient_whatsapp_id)
        )
    )).scalars().first()
    if patient is None:
        patient = Patient(
            office_id=office.id,
            whatsapp_id=body.patient_whatsapp_id,
            phone=body.patient_whatsapp_id,
            name=body.patient_name,
        )
        db.add(patient)
        await db.flush()

    start = dt_cls.strptime(body.start, "%Y-%m-%dT%H:%M").replace(tzinfo=MX_TIMEZONE)
    outcome = await book_appointment(
        db,
        office,
        patient_id=patient.id,
        start_dt=start,
        duration_min=body.duration_minutes,
        reason=body.reason,
        appt_type="follow_up",
        gcal_title=f"Cita: {patient.name}",
        gcal_description="Fixture del simulador",
        redis_client=redis_client,
    )
    if outcome.error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=outcome.error)
    outcome.appointment.status = body.status
    await db.commit()
    # A fixture is not a turn: its lock must not block the scenario's booking.
    from app.modules.scheduling.availability import release_slot_lock
    await release_slot_lock(office.id, start, redis_client)
    return {"id": str(outcome.appointment.id), "start": body.start}


@router.post("/fixtures/block")
async def sim_fixture_block(
    body: FixtureBlock,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Block part of the agenda, as the doctor would from the dashboard."""
    from datetime import datetime as dt_cls

    from app.core.constants import MX_TIMEZONE
    from app.modules.scheduling.blocks_service import create_block

    office = await _the_office(db)
    start = dt_cls.strptime(body.start, "%Y-%m-%dT%H:%M").replace(tzinfo=MX_TIMEZONE)
    end = dt_cls.strptime(body.end, "%Y-%m-%dT%H:%M").replace(tzinfo=MX_TIMEZONE)
    block = await create_block(office.id, start, end, body.reason, False, db, redis_client)
    return {"id": str(block.id)}


class FixtureGcalEvent(BaseModel):
    """A busy event straight in Google Calendar (the doctor's own agenda)."""

    start: str  # "YYYY-MM-DDTHH:MM", Mexico City time
    end: str
    title: str = "Junta (evento personal de prueba)"


@router.post("/fixtures/gcal_event")
async def sim_fixture_gcal_event(
    body: FixtureGcalEvent,
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Put an event in the connected calendar, as if the doctor had added it.

    Deleted by the next reset. 409 when no calendar is connected.
    """
    from datetime import datetime as dt_cls

    from app.core.constants import MX_TIMEZONE

    office = await _the_office(db)
    if not sim_gcal.calendar_connected(office):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no calendar connected")
    start = dt_cls.strptime(body.start, "%Y-%m-%dT%H:%M").replace(tzinfo=MX_TIMEZONE)
    end = dt_cls.strptime(body.end, "%Y-%m-%dT%H:%M").replace(tzinfo=MX_TIMEZONE)
    event_id = await sim_gcal.create_personal_event(db, redis_client, office, start, end, body.title)
    # Availability is cached per day; a new busy period must be seen at once.
    from app.modules.scheduling.availability import invalidate_availability_cache
    await invalidate_availability_cache(office.id, start.date(), redis_client)
    return {"id": event_id}


@router.get("/gcal/events")
async def sim_gcal_events(
    start: str,
    end: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Events in the connected calendar between two dates (YYYY-MM-DD), for
    scenario assertions: times in Mexico City wall time."""
    from datetime import datetime as dt_cls, time as time_cls

    from app.core.constants import MX_TIMEZONE

    office = await _the_office(db)
    if not sim_gcal.calendar_connected(office):
        return {"connected": False, "events": []}

    def local(value: dict) -> Optional[str]:
        raw = value.get("dateTime")
        if not raw:
            return value.get("date")
        return dt_cls.fromisoformat(raw.replace("Z", "+00:00")).astimezone(MX_TIMEZONE).strftime("%Y-%m-%dT%H:%M")

    time_min = dt_cls.combine(dt_cls.fromisoformat(start).date(), time_cls.min, tzinfo=MX_TIMEZONE)
    time_max = dt_cls.combine(dt_cls.fromisoformat(end).date(), time_cls.max, tzinfo=MX_TIMEZONE)
    events = await sim_gcal.list_events(db, office, time_min, time_max)
    return {
        "connected": True,
        "events": [
            {
                "id": e.get("id"),
                "summary": e.get("summary"),
                "start": local(e.get("start") or {}),
                "end": local(e.get("end") or {}),
                "status": e.get("status"),
                # "transparent" = does not block the slot (how cancellations look)
                "transparency": e.get("transparency", "opaque"),
                "color_id": e.get("colorId"),
            }
            for e in events
        ],
    }


class PurgeRequest(BaseModel):
    days_back: int = Field(default=30, ge=0, le=365)
    days_ahead: int = Field(default=90, ge=0, le=365)


@router.post("/gcal/purge")
async def sim_gcal_purge(body: PurgeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """One-off: delete events the app created in the test calendar, in a window.

    For leftovers from before resets cleaned up after themselves. Only events
    whose description carries an app marker are touched.
    """
    from datetime import timedelta

    office = await _the_office(db)
    if not sim_gcal.calendar_connected(office):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="no calendar connected")
    now = now_mx()
    return await sim_gcal.purge_marked_events(
        db, office, now - timedelta(days=body.days_back), now + timedelta(days=body.days_ahead)
    )


@router.get("/traces")
async def sim_traces(limit: int = 50, db: AsyncSession = Depends(get_db)) -> dict:
    """The latest assistant turn traces (ai_turn_traces), newest first."""
    from app.db.models import AiTurnTrace

    office = await _the_office(db)
    rows = (await db.execute(
        select(AiTurnTrace)
        .where(AiTurnTrace.office_id == office.id)
        .order_by(AiTurnTrace.created_at.desc())
        .limit(min(limit, 500))
    )).scalars().all()
    return {
        "traces": [
            {
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "channel": t.channel,
                "whatsapp_id": t.whatsapp_id,
                "model": t.model,
                "reasoning_effort": t.reasoning_effort,
                "user_text": t.user_text,
                "tool_calls": t.tool_calls or [],
                "grounding_violations": t.grounding_violations or [],
                "reply": t.reply,
                "outcome": t.outcome,
                "error": t.error,
                "llm_calls": t.llm_calls,
                "tokens_input": t.tokens_input,
                "tokens_output": t.tokens_output,
                "latency_ms": t.latency_ms,
            }
            for t in rows
        ]
    }


class CalendarRequest(BaseModel):
    """Which calendar the simulator should write its appointments into."""

    # Google's id for a secondary calendar, e.g. "abc123@group.calendar.google.com".
    # Omitted means "primary", which is almost never what you want here.
    calendar_id: Optional[str] = None


@router.get("/gcal/connect")
async def sim_gcal_connect(
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Start the Google Calendar consent flow for the simulator's office.

    The dashboard's equivalent is gated on a Supabase JWT and resolves the office
    from the token's subject. The simulator has no dashboard and no login, so it
    would be unreachable — but the gate exists to stop someone connecting a
    calendar to an office that is not theirs, and here there is exactly one
    office and the whole router already sits behind Basic auth.

    Everything after this is the ordinary flow: the same single-use state nonce,
    and the same callback, which resolves the office from that nonce rather than
    from anything the caller supplies.
    """
    from app.modules.google_calendar.auth import get_google_oauth_url

    office = await _the_office(db)
    # Come back to the simulator itself; there is no dashboard to land on.
    url = await get_google_oauth_url(office.id, redis_client, return_to="simulator")

    return {
        "auth_url": url,
        "note": (
            "open this in a browser and grant consent; point it at a throwaway "
            "calendar afterwards with POST /api/sim/gcal/calendar"
        ),
    }


@router.post("/gcal/calendar")
async def sim_gcal_calendar(
    body: CalendarRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Choose which calendar the simulator writes into.

    Point this at a disposable secondary calendar, never the doctor's real one.
    The simulator invents appointments and moves time, and resetting a scenario
    wipes the database but cannot reach into Google — so events pile up. With a
    calendar of its own, cleaning up is deleting that calendar; with `primary`,
    it is picking fake appointments out of someone's real week by hand.
    """
    office = await _the_office(db)
    office.google_calendar_id = body.calendar_id
    await db.commit()

    logger.info("sim_calendar_set", calendar_id=body.calendar_id)
    return {
        "calendar_id": office.google_calendar_id or "primary",
        "connected": bool(office.google_calendar_token),
    }


@router.get("/gcal/status")
async def sim_gcal_status(db: AsyncSession = Depends(get_db)) -> dict:
    """Whether the simulator has a calendar connected, and which one."""
    office = await _the_office(db)
    return {
        "connected": bool(office.google_calendar_token),
        "calendar_id": office.google_calendar_id or "primary (cámbialo)",
        "redirect_uri_configured": settings.google_redirect_uri,
    }


# --------------------------------------------------------------------------- #
# Which models the operator may choose from
# --------------------------------------------------------------------------- #

# Everything the account can see that is not a chat model. Filtering by what a
# model *is not* keeps new releases in the list automatically, which is the whole
# reason this is fetched instead of hardcoded.
_NOT_CHAT = (
    "audio", "realtime", "transcribe", "tts", "embedding", "image", "search",
    "moderation", "instruct", "dall-e", "whisper", "codex", "sora", "live",
)
_CHAT_PREFIXES = ("gpt-", "o1", "o3", "o4")

# Dated snapshots (gpt-5.4-2026-03-05) are the same model as their alias and only
# add noise to a dropdown.
_DATED = __import__("re").compile(r"-\d{4}-\d{2}-\d{2}$")

# A shortlist for this product, offered first. The axis that matters here is
# cost and latency against instruction-following: a patient is waiting on
# WhatsApp, and a turn spends several tool calls. So it spans the range rather
# than picking a winner — that is what the operator is here to decide.
#
# "pro" variants are deliberately left out of the shortlist (still selectable
# below): they are built for long deliberation, which is the opposite of what a
# chat turn needs. Anything past gpt-5.4 is ordered by version, not by measured
# behaviour — nobody here has benchmarked them for this task, which is precisely
# what the simulator is for.
RECOMMENDED = [
    "gpt-4.1-mini",
    "gpt-5-mini",
    "gpt-5.4-nano",
    "gpt-5.4-mini",
    "gpt-4.1",
    "gpt-5.4",
    "gpt-5.5",
    "gpt-5.6-luna",
    "gpt-5.6-sol",
    "gpt-6-luna",
]

# The second tier of the dropdown. Also a fixed list rather than "everything
# else the account can see": that was forty entries, most of which nobody should
# ever pick for this product, and a dropdown that long stops being a choice and
# starts being a search. These eight are the ones that add an axis the shortlist
# above does not already cover — the cheap floor, the base of each family, the
# variants the shortlist only half-covers, and one small reasoning model.
#
# Deliberately left out: `-pro` variants (built for long deliberation, the
# opposite of a WhatsApp turn), `-chat-latest` aliases (a moving target, and not
# a stable base for function tools), the intermediate 5.x versions (they sit
# between models already offered and answer no question the shortlist cannot),
# the larger o-series (o1/o1-pro/o3 are minutes-per-turn slow here), and the
# 3.5/4/4-turbo generation (too weak at tool use to be worth a comparison).
OTHERS = [
    "gpt-4o-mini",
    "gpt-4.1-nano",
    "gpt-5-nano",
    "gpt-5",
    "gpt-5.6-terra",
    "gpt-6-sol",
    "gpt-6-astra",
    "o4-mini",
]

MODELS_CACHE_KEY = "sim:openai_models"
MODELS_CACHE_TTL = 60 * 60


def _is_chat_model(model_id: str) -> bool:
    if not model_id.startswith(_CHAT_PREFIXES):
        return False
    if any(token in model_id for token in _NOT_CHAT):
        return False
    return not _DATED.search(model_id)


@router.get("/models")
async def sim_models(redis_client: aioredis.Redis = Depends(get_redis)) -> dict:
    """The models this account can actually use.

    Asked of OpenAI rather than hardcoded, so the list is true today and stays
    true when a new model ships — a stale dropdown would quietly stop the
    operator from testing the thing they came to test.

    Falls back to the shortlist if the call fails, so a network hiccup leaves the
    simulator usable instead of empty.
    """
    from app.modules.ai.openai_service import is_reasoning_first_model

    cached = await redis_client.get(MODELS_CACHE_KEY)
    if cached:
        available = json.loads(cached)
    else:
        available = []
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {settings.open_ai_key}"},
                )
                r.raise_for_status()
                available = sorted(
                    m["id"] for m in r.json()["data"] if _is_chat_model(m["id"])
                )
            await redis_client.setex(
                MODELS_CACHE_KEY, MODELS_CACHE_TTL, json.dumps(available)
            )
        except Exception as e:
            logger.warning("sim_models_fetch_failed", error=str(e))

    if not available:
        available = RECOMMENDED + OTHERS

    def describe(model_id: str) -> dict:
        return {
            "provider": "openai",
            "model": model_id,
            # Reasoning-first models go to /v1/responses and take a thinking
            # level; the UI only offers that control for these.
            "reasoning": is_reasoning_first_model(model_id),
        }

    shortlist = [describe(m) for m in RECOMMENDED if m in available]
    rest = [describe(m) for m in OTHERS if m in available]

    return {
        "recommended": shortlist,
        "others": rest,
        "anthropic": {
            "provider": "anthropic",
            "model": settings.anthropic_ai_model,
            "reasoning": False,
            # Offering a provider with no key would fail as a confusing auth
            # error mid-conversation; the UI greys it out instead.
            "available": bool(settings.anthropic_api_key and settings.anthropic_ai_model),
        },
        "configured": current_selection().model,
        # So the dropdowns can open on what this environment actually runs.
        # A simulator whose first turn silently uses a different thinking level
        # than test does is worse than no default at all.
        "configured_reasoning_effort": current_selection().reasoning_effort,
    }


# --------------------------------------------------------------------------- #
# What this practice is
# --------------------------------------------------------------------------- #

# 0=Sunday in AvailabilitySchedule; DAYS_ES starts on Monday.
_DAY_NAMES = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]

# What each automatic message is, in the operator's words rather than the
# enum's. Someone judging whether the bot behaved should not have to know that
# "at_time" is the waiting-room check-in.
_REMINDER_LABELS = {
    "week_before": "Recordatorio una semana antes",
    "day_before": "Recordatorio de la víspera, con botones para confirmar",
    "6h": "Recordatorio el mismo día",
    "doctor_brief": "Resumen para el doctor antes de la consulta",
    "at_time": "Pregunta al paciente si ya llegó",
    "post_appointment": "Seguimiento después de la consulta",
}


def _offset_label(minutes: int) -> str:
    """'2 días antes', '15 minutos después' — signed relative to the start."""
    if minutes == 0:
        return "a la hora de la cita"
    after = minutes > 0
    minutes = abs(minutes)
    if minutes % (60 * 24) == 0:
        amount, unit = minutes // (60 * 24), "día"
    elif minutes % 60 == 0:
        amount, unit = minutes // 60, "hora"
    else:
        amount, unit = minutes, "minuto"
    plural = "" if amount == 1 else "s"
    return f"{amount} {unit}{plural} {'después' if after else 'antes'}"


@router.get("/office")
async def sim_office(db: AsyncSession = Depends(get_db)) -> dict:
    """How this practice is configured, in readable form.

    The simulator is for judging whether the assistant answered *correctly*, and
    that is impossible without knowing what the practice actually offers. Someone
    testing blind cannot tell a right price from an invented one, or a legitimate
    "no atiendo ese día" from a bug.

    Insurer and intake ids are resolved to their labels here for the same reason:
    "gnp" is a database value, "GNP Seguros" is what the patient would hear.
    """
    from sqlalchemy import asc

    from app.core.catalogs import insurer_labels, intake_labels, specialty_label
    from app.db.models import AvailabilitySchedule, ReminderRule

    office = await _the_office(db)

    schedules = (
        await db.execute(
            select(AvailabilitySchedule)
            .where(
                AvailabilitySchedule.office_id == office.id,
                AvailabilitySchedule.is_active.is_(True),
            )
            .order_by(asc(AvailabilitySchedule.day_of_week), asc(AvailabilitySchedule.start_time))
        )
    ).scalars().all()

    by_day: dict[str, list[str]] = {}
    for row in schedules:
        day = _DAY_NAMES[row.day_of_week]
        by_day.setdefault(day, []).append(
            f"{row.start_time.strftime('%H:%M')}–{row.end_time.strftime('%H:%M')}"
        )

    rules = (
        await db.execute(
            select(ReminderRule).where(
                ReminderRule.office_id == office.id, ReminderRule.enabled.is_(True)
            )
        )
    ).scalars().all()

    intake = office.intake_questions or {}
    custom = intake.get("custom") if isinstance(intake, dict) else None
    preguntas = intake_labels(intake.get("preset") if isinstance(intake, dict) else None)
    if custom:
        preguntas = preguntas + [custom]

    return {
        "nombre": office.name,
        "doctor": " ".join(
            filter(None, [office.doctor_first_name, office.doctor_last_name])
        ),
        "especialidad": specialty_label(office.specialty) or office.specialty,
        "direccion": ", ".join(filter(None, [office.address, office.city, office.state])),
        "asistente": {
            "nombre": office.assistant_name,
            "tono": office.assistant_tone,
        },
        "horarios": [{"dia": d, "bloques": b} for d, b in by_day.items()],
        "duraciones": {
            "primera_vez": office.new_patient_duration_min,
            "seguimiento": office.returning_patient_duration_min,
        },
        "servicios": office.services or [],
        "costos": {
            "primera_vez": office.new_patient_cost,
            "seguimiento": office.returning_patient_cost,
        },
        "seguros": {
            "acepta": office.accepts_insurance,
            "lista": insurer_labels(office.insurances),
        },
        "sintomas_de_urgencia": office.emergency_symptoms or [],
        "preguntas_antes_de_la_cita": preguntas,
        "mensajes_automaticos": sorted(
            (
                {
                    "que": _REMINDER_LABELS.get(r.reminder_type, r.reminder_type),
                    "cuando": _offset_label(r.offset_minutes),
                    "orden": r.offset_minutes,
                }
                for r in rules
            ),
            key=lambda r: r["orden"],
        ),
        "telefonos": {
            "paciente_por_defecto": "5215550000001",
            "doctor": office.owner_phone,
            "secretaria": office.secondary_owner_phone,
        },
        "calendario_conectado": bool(office.google_calendar_token),
    }
