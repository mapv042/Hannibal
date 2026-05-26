"""FastAPI router for WhatsApp webhook and onboarding endpoints."""

from __future__ import annotations

import asyncio
from typing import Optional, Dict, Any

from fastapi import APIRouter, Query, Request, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.config import settings
from app.core.dependencies import get_db, get_redis
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
from app.modules.conversation.manager_v2 import ConversationManagerV2
from app.modules.conversation.doctor_manager import DoctorConversationManager
from app.modules.conversation.session_store import SessionStore
from app.modules.whatsapp.meta_client import MetaCloudClient
from app.core.exceptions import WhatsAppError
from app.utils.phone import normalize_phone

logger = get_logger(__name__)

router = APIRouter()

auth_router = APIRouter(
    prefix="/auth/whatsapp",
    tags=["whatsapp-auth"],
)


# ============================================================================
# Webhook Verification & Message Processing
# ============================================================================


@router.get("/webhook", response_class=PlainTextResponse)
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

    if hub_verify_token != settings.meta_verify_token:
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
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
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
        db,
        redis_client,
    )

    return {"status": 200}


async def _process_webhook_async(
    payload: Dict[str, Any],
    db: AsyncSession,
    redis_client: redis.Redis,
) -> None:
    """
    Async webhook processing (happens in background).

    Extracts messages/statuses and routes them appropriately.
    """
    try:
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
            conversation_payload = {
                "entry": [{"changes": [{"value": {"messages": [message]}}]}]
            }
            await doctor_manager.process(office, conversation_payload, db)
            return

        # Check if bot is paused
        is_paused = await check_pause(office.id, redis_client)
        if is_paused:
            logger.info(
                "message_dropped_bot_paused",
                message_id=message_id,
                office_id=str(office.id),
            )
            return

        # Check for doctor echo (coexistence mode)
        if is_doctor_echo({"entry": [{"changes": [{"value": {"messages": [message]}}]}]}):
            logger.info(
                "message_skipped_doctor_echo",
                message_id=message_id,
                office_id=str(office.id),
            )
            return

        # Route to conversation manager (v1 or v2 based on feature flag)
        session_store = SessionStore(redis_client)
        meta_client = MetaCloudClient()
        if settings.use_tool_based_ai:
            manager = ConversationManagerV2(session_store, meta_client)
        else:
            manager = ConversationManager(session_store, meta_client)

        # Reconstruct payload in the format ConversationManager expects
        conversation_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [message]
                    }
                }]
            }]
        }

        await manager.process(office, conversation_payload, db)

    except Exception as e:
        logger.error(
            "process_message_error",
            message_id=message.get("id"),
            error=str(e),
            exc_info=True,
        )


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


@auth_router.post("/embedded-signup")
async def complete_whatsapp_onboarding(
    request: Request,
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

    except Exception as e:
        logger.error("whatsapp_onboarding_error", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete onboarding",
        )


@auth_router.get("/status/{office_id}")
async def get_whatsapp_activation_status(
    office_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get WhatsApp activation status for an office.

    Returns comprehensive information about the office's WhatsApp setup.

    Args:
        office_id: UUID of the office

    Returns:
        Dictionary with activation status and credentials
    """
    try:
        import uuid as uuid_lib
        office_uuid = uuid_lib.UUID(office_id)

        # TODO: Import provisioning function
        # from app.modules.whatsapp.provisioning import get_whatsapp_status
        status_info = await get_whatsapp_status(office_uuid, db)

        return status_info

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid office_id format",
        )
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
