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
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_selection import clear_ai_override, current_selection, set_ai_override
from app.core.dependencies import get_db, get_redis
from app.db.models import Office
from app.modules.sim.auth import require_sim_auth
from app.modules.sim.runner import (
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
            set_ai_override(body.provider or "openai", body.model)
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
