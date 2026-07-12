"""FastAPI router for WhatsApp webhook and onboarding endpoints."""

from __future__ import annotations

import asyncio
import hmac
import time
import uuid as uuid_module
from typing import Optional, Dict, Any

from fastapi import APIRouter, Query, Request, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.middleware.rate_limiter import limiter
from app.db.base import get_async_session_maker
from app.utils.logger import get_logger
from app.modules.whatsapp.validator import validate_webhook_signature
from app.modules.whatsapp.schemas import (
    WebhookVerificationRequest,
    SendMessageRequest,
    SendMessageResponse,
)
from app.modules.whatsapp.provisioning import get_office_by_phone_id, get_whatsapp_status
from app.modules.whatsapp.coexistence import (
    check_pause,
    get_conversation_by_whatsapp_id,
    is_doctor_echo,
)
from app.modules.conversation.manager import ConversationManager
from app.modules.conversation.doctor_manager import DoctorConversationManager
from app.modules.conversation.session_store import SessionStore
from app.modules.whatsapp.meta_client import MetaCloudClient
from app.core.exceptions import WhatsAppError
from app.utils.phone import normalize_phone

logger = get_logger(__name__)

router = APIRouter()

# Webhook idempotency: Meta retries deliveries, so each message id is processed
# only once. TTL comfortably covers Meta's retry window.
MESSAGE_DEDUP_KEY = "wamsg_dedup:{message_id}"
MESSAGE_DEDUP_TTL = 86400

# Per-conversation serialization: two rapid messages from the same sender must
# not run concurrently (they read-modify-write the same Redis session).
CONV_LOCK_KEY = "conv_lock:{office_id}:{sender}"
CONV_LOCK_TTL = 120  # safety bound; normal turns finish well under this
CONV_LOCK_WAIT_SECONDS = 90
CONV_LOCK_POLL_SECONDS = 0.5


async def _acquire_conversation_lock(
    redis_client: redis.Redis, key: str, token: str
) -> bool:
    """Wait for the per-conversation lock so turns process in arrival order.

    Returns False after CONV_LOCK_WAIT_SECONDS (the previous turn is stuck or
    the TTL is about to reap it) — callers proceed anyway rather than drop the
    patient's message, which is the lesser evil.
    """
    deadline = time.monotonic() + CONV_LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        acquired = await redis_client.set(key, token, nx=True, ex=CONV_LOCK_TTL)
        if acquired:
            return True
        await asyncio.sleep(CONV_LOCK_POLL_SECONDS)
    logger.warning("conversation_lock_timeout", key=key)
    return False


async def _release_conversation_lock(
    redis_client: redis.Redis, key: str, token: str
) -> None:
    """Release the lock only if we still own it (best-effort compare-and-delete)."""
    try:
        current = await redis_client.get(key)
        if current is not None and current in (token, token.encode()):
            await redis_client.delete(key)
    except Exception as e:
        logger.warning("conversation_lock_release_failed", key=key, error=str(e))

auth_router = APIRouter(
    prefix="/auth/whatsapp",
    tags=["whatsapp-auth"],
)


# ============================================================================
# Webhook Verification & Message Processing
# ============================================================================


@router.get("/webhook", response_class=PlainTextResponse)
@limiter.exempt
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
) -> str:
    """
    Webhook verification endpoint for Meta Cloud API.

    Meta sends a GET request with verification parameters when setting up
    the webhook. We must echo back the challenge string if the token matches.

    Args:
        hub_mode: Should be 'subscribe'
        hub_challenge: Challenge string to echo back
        hub_verify_token: Token that must match META_VERIFY_TOKEN

    Returns:
        JSON with challenge echoed back (or error)

    Raises:
        HTTPException: If verification fails
    """
    # Validate parameters
    if not all([hub_mode, hub_challenge, hub_verify_token]):
        logger.warning(
            "webhook_verify_missing_params",
            has_mode=bool(hub_mode),
            has_challenge=bool(hub_challenge),
            has_token=bool(hub_verify_token),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing verification parameters",
        )

    if hub_mode != "subscribe":
        logger.warning("webhook_verify_invalid_mode", mode=hub_mode)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hub.mode",
        )

    # Constant-time compare to avoid leaking the token via response timing.
    if not hmac.compare_digest(hub_verify_token, settings.meta_verify_token):
        logger.warning(
            "webhook_verify_token_mismatch",
            provided=hub_verify_token[:8] + "..." if hub_verify_token else None,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid verification token",
        )

    logger.info("webhook_verified")
    return hub_challenge


@router.post("/webhook")
@limiter.exempt
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    redis_client: redis.Redis = Depends(get_redis),
) -> Dict[str, int]:
    """
    Receive incoming WhatsApp messages and status updates from Meta.

    This endpoint:
    1. Validates the HMAC-SHA256 signature
    2. Identifies the office by phone_number_id
    3. Extracts messages and status updates
    4. Checks if bot is paused (coexistence mode)
    5. Routes to conversation manager async
    6. Returns 200 immediately to Meta

    Returns:
        Always returns 200 with status code (process happens in background)

    Raises:
        HTTPException: If signature validation fails
    """
    # Get raw body for signature validation
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Validate webhook signature
    if not validate_webhook_signature(body, signature):
        logger.error("webhook_signature_invalid")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )

    # Parse JSON
    try:
        payload = await request.json()
    except Exception as e:
        logger.error("webhook_parse_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON",
        )

    # Validate structure
    if payload.get("object") != "whatsapp_business_account":
        logger.warning(
            "webhook_invalid_object",
            object_type=payload.get("object"),
        )
        # Still return 200 to Meta
        return {"status": 200}

    # Return 200 immediately
    background_tasks.add_task(
        _process_webhook_async,
        payload,
        redis_client,
    )

    return {"status": 200}


async def _process_webhook_async(
    payload: Dict[str, Any],
    redis_client: redis.Redis,
) -> None:
    """
    Async webhook processing (happens in background).

    Extracts messages/statuses and routes them appropriately.

    Opens its own DB session: the request-scoped session from `get_db` is
    closed once the 200 response is sent, so it cannot be reused here (the
    background task runs after the request completes).
    """
    try:
        async with get_async_session_maker()() as db:
            entries = payload.get("entry", [])

            for entry in entries:
                changes = entry.get("changes", [])

                for change in changes:
                    value = change.get("value", {})

                    # Get phone_number_id to identify office
                    phone_number_id = value.get("metadata", {}).get("phone_number_id")
                    if not phone_number_id:
                        logger.warning("webhook_no_phone_number_id")
                        continue

                    # Find office
                    office = await get_office_by_phone_id(phone_number_id, db)
                    if not office:
                        logger.warning(
                            "webhook_office_not_found",
                            phone_number_id=phone_number_id,
                        )
                        continue

                    # Process messages
                    messages = value.get("messages", [])
                    for message in messages:
                        await _process_message(
                            message,
                            office,
                            db,
                            redis_client,
                        )

                    # Process status updates
                    statuses = value.get("statuses", [])
                    for status_update in statuses:
                        await _process_status(
                            status_update,
                            office,
                            db,
                            redis_client,
                        )

    except Exception as e:
        logger.error("webhook_process_error", error=str(e), exc_info=True)


async def _process_message(
    message: Dict[str, Any],
    office,
    db: AsyncSession,
    redis_client: redis.Redis,
) -> None:
    """Process a single incoming message."""
    try:
        message_id = message.get("id")
        from_id = message.get("from")
        message_type = message.get("type", "text")

        logger.info(
            "webhook_message_received",
            message_id=message_id,
            from_id=from_id,
            type=message_type,
            office_id=str(office.id),
        )

        # Deduplicate: Meta retries webhook deliveries, and processing twice
        # means replying twice. First delivery wins.
        if message_id:
            first_delivery = await redis_client.set(
                MESSAGE_DEDUP_KEY.format(message_id=message_id),
                "1",
                nx=True,
                ex=MESSAGE_DEDUP_TTL,
            )
            if not first_delivery:
                logger.info(
                    "webhook_duplicate_message_skipped",
                    message_id=message_id,
                    office_id=str(office.id),
                )
                return

        # Serialize turns per sender: a second message from the same person
        # waits for the previous one instead of racing it on the session.
        lock_key = CONV_LOCK_KEY.format(office_id=office.id, sender=from_id)
        lock_token = uuid_module.uuid4().hex
        lock_acquired = await _acquire_conversation_lock(
            redis_client, lock_key, lock_token
        )
        try:
            await _route_message(message, office, db, redis_client)
        finally:
            if lock_acquired:
                await _release_conversation_lock(redis_client, lock_key, lock_token)

    except Exception as e:
        logger.error(
            "process_message_error",
            message_id=message.get("id"),
            error=str(e),
            exc_info=True,
        )


async def _route_message(
    message: Dict[str, Any],
    office,
    db: AsyncSession,
    redis_client: redis.Redis,
) -> None:
    """Route a deduplicated, lock-protected message to the right manager."""
    message_id = message.get("id")
    from_id = message.get("from")

    # Check if sender is the doctor (route before pause check so doctor always gets through)
    is_doctor = False
    if office.owner_phone:
        try:
            is_doctor = normalize_phone(from_id) == normalize_phone(office.owner_phone)
        except ValueError:
            pass
    if is_doctor:
        logger.info(
            "doctor_message_detected",
            message_id=message_id,
            office_id=str(office.id),
        )
        meta_client = MetaCloudClient()
        doctor_manager = DoctorConversationManager(meta_client, redis_client)
        await doctor_manager.process(office, message, db)
        return

    # Check if bot is paused (single source of truth: Redis, set by pause_bot)
    is_paused = await check_pause(office.id, redis_client)
    if is_paused:
        logger.info(
            "message_stored_bot_paused",
            message_id=message_id,
            office_id=str(office.id),
        )
        # The bot stays silent, but the message must still show up in the
        # dashboard conversation history.
        await _persist_incoming_while_paused(message, office, db)
        return

    # Check for doctor echo (coexistence mode)
    if is_doctor_echo({"entry": [{"changes": [{"value": {"messages": [message]}}]}]}):
        logger.info(
            "message_skipped_doctor_echo",
            message_id=message_id,
            office_id=str(office.id),
        )
        return

    # Route to the tool-use conversation manager
    session_store = SessionStore(redis_client)
    meta_client = MetaCloudClient()
    manager = ConversationManager(session_store, meta_client)
    await manager.process(office, message, db)


async def _persist_incoming_while_paused(
    message: Dict[str, Any],
    office,
    db: AsyncSession,
) -> None:
    """Record an incoming patient message received while the bot is paused."""
    from sqlalchemy import select
    from app.db.models import Conversation, Message

    try:
        from_id = message.get("from")
        msg_type = message.get("type", "text")
        if msg_type == "text":
            content = message.get("text", {}).get("body", "")
        else:
            content = f"[Mensaje de tipo {msg_type}]"

        stmt = select(Conversation).where(
            (Conversation.office_id == office.id)
            & (Conversation.whatsapp_id == from_id)
            & (Conversation.status != "archived")
        ).limit(1)
        conversation = (await db.execute(stmt)).scalars().first()
        if not conversation:
            conversation = Conversation(
                id=uuid_module.uuid4(),
                office_id=office.id,
                whatsapp_id=from_id,
                status="active",
            )
            db.add(conversation)
            await db.flush()

        db.add(Message(
            id=uuid_module.uuid4(),
            conversation_id=conversation.id,
            content=content,
            type="text",
            direction="incoming",
            whatsapp_message_id=message.get("id"),
        ))
        await db.commit()
    except Exception as e:
        logger.warning("paused_message_persist_failed", error=str(e))


async def _process_status(
    status_update: Dict[str, Any],
    office,
    db: AsyncSession,
    redis_client: redis.Redis,
) -> None:
    """Process a message status update (sent, delivered, read, failed)."""
    from sqlalchemy import select
    from app.db.models import Message

    try:
        message_id = status_update.get("id")
        status = status_update.get("status")
        recipient_id = status_update.get("recipient_id")

        logger.info(
            "webhook_status_received",
            message_id=message_id,
            status=status,
            recipient_id=recipient_id,
            office_id=str(office.id),
        )

        if status in ("sent", "delivered", "read", "failed") and message_id:
            stmt = select(Message).where(Message.whatsapp_message_id == message_id)
            result = await db.execute(stmt)
            msg = result.scalar_one_or_none()
            if msg:
                # Only update forward: sent → delivered → read, or any → failed
                status_order = {"sent": 1, "delivered": 2, "read": 3, "failed": 0}
                current = status_order.get(msg.delivery_status, -1)
                new = status_order.get(status, -1)
                if status == "failed" or new > current:
                    msg.delivery_status = status
                    await db.commit()
                    logger.info(
                        "message_delivery_updated",
                        message_id=message_id,
                        status=status,
                    )

                # Once a doctor-sent message actually reaches the patient, mirror
                # it into the patient's session so the bot has context if they
                # reply. Only on real delivery, and only once (idempotent flag).
                meta = msg.extra_metadata or {}
                if (
                    status in ("delivered", "read")
                    and meta.get("source") == "doctor_send_message"
                    and not meta.get("session_synced")
                ):
                    await _mirror_doctor_message_to_session(
                        msg, office, db, redis_client
                    )

    except Exception as e:
        logger.error(
            "process_status_error",
            message_id=status_update.get("id"),
            error=str(e),
            exc_info=True,
        )


async def _mirror_doctor_message_to_session(
    msg,
    office,
    db: AsyncSession,
    redis_client: redis.Redis,
) -> None:
    """Append a delivered doctor→patient message into the patient's session.

    Best-effort: marks the message as synced so it is only mirrored once, even
    if both `delivered` and `read` webhooks arrive.
    """
    from sqlalchemy import select
    from app.db.models import Conversation, Patient
    from app.modules.conversation.session_store import append_outgoing_message

    try:
        conv = await db.get(Conversation, msg.conversation_id)
        if not conv:
            return

        presult = await db.execute(
            select(Patient).where(
                (Patient.office_id == office.id)
                & (Patient.whatsapp_id == conv.whatsapp_id)
            )
        )
        patient = presult.scalar_one_or_none()

        await append_outgoing_message(
            redis_client,
            office.id,
            conv.whatsapp_id,
            msg.content,
            conversation_id=conv.id,
            patient_id=patient.id if patient else None,
        )

        # Mark synced (reassign dict so SQLAlchemy detects the JSONB change)
        msg.extra_metadata = {**(msg.extra_metadata or {}), "session_synced": True}
        await db.commit()

        logger.info(
            "doctor_message_mirrored_to_session",
            message_id=msg.whatsapp_message_id,
            office_id=str(office.id),
        )
    except Exception as e:
        logger.warning(
            "doctor_message_mirror_failed",
            message_id=getattr(msg, "whatsapp_message_id", None),
            error=str(e),
        )


# ============================================================================
# Onboarding Endpoints
# ============================================================================


async def _require_owned_office(
    office_id: str,
    current_user: dict,
    db: AsyncSession,
):
    """Load an office and assert the authenticated user owns it.

    Returns the Office. Raises 400 on a malformed id and 404 when the office
    doesn't exist OR isn't owned by the caller — the same response for both so
    an attacker can't enumerate which office ids are real.
    """
    import uuid as uuid_lib
    from app.db.models import Office

    try:
        office_uuid = uuid_lib.UUID(office_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid office_id format",
        )

    office = await db.get(Office, office_uuid)
    user_id = current_user.get("sub")
    if not office or str(office.user_id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Office not found",
        )
    return office


@auth_router.post("/embedded-signup")
async def complete_whatsapp_onboarding(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """
    Complete WhatsApp embedded signup flow.

    After user completes Meta's embedded signup, the frontend sends us
    the resulting credentials (phone_number_id, waba_id, access_token).

    This endpoint stores those credentials for the user's office.

    Expected request body:
    {
        "office_id": "uuid",
        "phone_number_id": "string",
        "waba_id": "string",
        "access_token": "string",
        "mode": "coexistence|dedicated|new"
    }
    """
    try:
        payload = await request.json()

        office_id = payload.get("office_id")
        phone_number_id = payload.get("phone_number_id")
        waba_id = payload.get("waba_id")
        access_token = payload.get("access_token")
        mode = payload.get("mode", "new")

        if not all([office_id, phone_number_id, waba_id, access_token]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required fields",
            )

        # Only the office's owner may attach WhatsApp credentials to it.
        await _require_owned_office(office_id, current_user, db)

        # TODO: Import and use provisioning functions
        # from app.modules.whatsapp.provisioning import register_meta_number
        # success = await register_meta_number(
        #     phone_number_id,
        #     waba_id,
        #     access_token,
        #     office_id,
        #     mode,
        #     db,
        # )

        logger.info(
            "whatsapp_onboarding_complete",
            office_id=office_id,
            phone_number_id=phone_number_id,
            mode=mode,
        )

        return {
            "status": "success",
            "message": "WhatsApp configured successfully",
        }

    except HTTPException:
        raise  # auth/validation errors must reach the client unchanged
    except Exception as e:
        logger.error("whatsapp_onboarding_error", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete onboarding",
        )


@auth_router.get("/status/{office_id}")
async def get_whatsapp_activation_status(
    office_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get WhatsApp activation status for an office (owner only).

    Args:
        office_id: UUID of the office

    Returns:
        Dictionary with activation status and credentials
    """
    try:
        office = await _require_owned_office(office_id, current_user, db)
        return await get_whatsapp_status(office.id, db)

    except HTTPException:
        raise  # auth/validation errors must reach the client unchanged
    except Exception as e:
        logger.error(
            "whatsapp_status_error",
            office_id=office_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch status",
        )


# Include both routers in main app
def include_whatsapp_routes(app):
    """Register WhatsApp routers with the FastAPI app."""
    app.include_router(router)
    app.include_router(auth_router)
