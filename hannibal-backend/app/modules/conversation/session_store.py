"""Redis-based session storage for conversation state."""

from __future__ import annotations

import json
import uuid as uuid_module
from datetime import datetime
from typing import Optional

import redis.asyncio as redis
from pydantic import ValidationError

from app.config import settings
from app.utils.logger import get_logger
from app.core.exceptions import SessionStoreError
from app.modules.conversation.schemas import SessionContext

logger = get_logger(__name__)

# Session TTL in seconds (24 hours)
DEFAULT_SESSION_TTL = 86400


class SessionStore:
    """
    Redis-based session store for WhatsApp conversation state.

    Manages session lifecycle with automatic expiration and type safety.
    """

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        redis_url: str = settings.redis_url,
        ttl: int = DEFAULT_SESSION_TTL,
    ):
        """
        Initialize session store.

        Args:
            redis_client: Existing Redis client instance (preferred)
            redis_url: Redis connection URL (used if no client provided)
            ttl: Session TTL in seconds (default: 24 hours)
        """
        self.redis_url = redis_url
        self.ttl = ttl
        self.redis_client: Optional[redis.Redis] = redis_client

    async def _get_client(self) -> redis.Redis:
        """
        Lazy-load Redis client.

        Returns:
            Redis async client
        """
        if self.redis_client is None:
            self.redis_client = await redis.from_url(self.redis_url, decode_responses=True)
        return self.redis_client

    @staticmethod
    def _make_key(whatsapp_id: str, office_id: str) -> str:
        """
        Generate Redis key for a session.

        Args:
            whatsapp_id: WhatsApp sender ID
            office_id: Office UUID

        Returns:
            Redis key string
        """
        return f"session:{whatsapp_id}:{office_id}"

    async def get_session(
        self,
        whatsapp_id: str,
        office_id: str,
    ) -> Optional[SessionContext]:
        """
        Retrieve a session from Redis.

        Args:
            whatsapp_id: WhatsApp sender ID
            office_id: Office UUID as string

        Returns:
            SessionContext if found, None if expired or doesn't exist

        Raises:
            SessionStoreError: If retrieval fails
        """
        try:
            client = await self._get_client()
            key = self._make_key(whatsapp_id, office_id)

            session_json = await client.get(key)

            if not session_json:
                logger.debug(
                    "session_not_found",
                    whatsapp_id=whatsapp_id,
                    office_id=office_id,
                )
                return None

            session_data = json.loads(session_json)

            # Convert string UUIDs back to UUID objects for Pydantic
            if "conversation_id" in session_data:
                session_data["conversation_id"] = uuid_module.UUID(
                    session_data["conversation_id"]
                )
            if "office_id" in session_data:
                session_data["office_id"] = uuid_module.UUID(
                    session_data["office_id"]
                )
            if "patient_id" in session_data and session_data["patient_id"]:
                session_data["patient_id"] = uuid_module.UUID(session_data["patient_id"])
            if "active_appointment_id" in session_data and session_data["active_appointment_id"]:
                session_data["active_appointment_id"] = uuid_module.UUID(
                    session_data["active_appointment_id"]
                )

            session = SessionContext(**session_data)

            logger.debug(
                "session_retrieved",
                whatsapp_id=whatsapp_id,
                office_id=office_id,
                status=session.status,
            )

            return session

        except ValidationError as e:
            logger.error(
                "session_validation_error",
                error=str(e),
                whatsapp_id=whatsapp_id,
                office_id=office_id,
            )
            raise SessionStoreError(
                f"Invalid session data: {str(e)}"
            ) from e
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(
                "session_parse_error",
                error=str(e),
                whatsapp_id=whatsapp_id,
                office_id=office_id,
            )
            raise SessionStoreError(
                f"Failed to parse session data: {str(e)}"
            ) from e
        except Exception as e:
            logger.error(
                "session_retrieval_failed",
                error=str(e),
                whatsapp_id=whatsapp_id,
                office_id=office_id,
            )
            raise SessionStoreError(
                f"Failed to retrieve session: {str(e)}"
            ) from e

    async def save_session(
        self,
        whatsapp_id: str,
        office_id: str,
        session: SessionContext,
        ttl: Optional[int] = None,
    ) -> None:
        """
        Save a session to Redis.

        Args:
            whatsapp_id: WhatsApp sender ID
            office_id: Office UUID as string
            session: SessionContext to save
            ttl: Optional TTL override (default: instance TTL)

        Raises:
            SessionStoreError: If save fails
        """
        try:
            client = await self._get_client()
            key = self._make_key(whatsapp_id, office_id)

            # Convert Pydantic model to dict with UUID strings
            session_dict = session.model_dump()
            session_dict["conversation_id"] = str(session.conversation_id)
            session_dict["office_id"] = str(session.office_id)
            if session.patient_id:
                session_dict["patient_id"] = str(session.patient_id)
            if session.active_appointment_id:
                session_dict["active_appointment_id"] = str(session.active_appointment_id)

            session_json = json.dumps(session_dict, default=str)
            ttl_value = ttl or self.ttl

            await client.setex(
                key,
                ttl_value,
                session_json,
            )

            logger.debug(
                "session_saved",
                whatsapp_id=whatsapp_id,
                office_id=office_id,
                ttl=ttl_value,
            )

        except Exception as e:
            logger.error(
                "session_save_failed",
                error=str(e),
                whatsapp_id=whatsapp_id,
                office_id=office_id,
            )
            raise SessionStoreError(f"Failed to save session: {str(e)}") from e

    async def delete_session(
        self,
        whatsapp_id: str,
        office_id: str,
    ) -> None:
        """
        Delete a session from Redis.

        Args:
            whatsapp_id: WhatsApp sender ID
            office_id: Office UUID as string

        Raises:
            SessionStoreError: If deletion fails
        """
        try:
            client = await self._get_client()
            key = self._make_key(whatsapp_id, office_id)

            await client.delete(key)

            logger.info(
                "session_deleted",
                whatsapp_id=whatsapp_id,
                office_id=office_id,
            )

        except Exception as e:
            logger.error(
                "session_delete_failed",
                error=str(e),
                whatsapp_id=whatsapp_id,
                office_id=office_id,
            )
            raise SessionStoreError(f"Failed to delete session: {str(e)}") from e

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()
            self.redis_client = None


async def append_outgoing_message(
    redis_client: redis.Redis,
    office_id,
    whatsapp_id: str,
    content: str,
    *,
    conversation_id,
    patient_id=None,
) -> None:
    """Append an outgoing (assistant) turn to the patient's session.

    Used to mirror a message the doctor sent to the patient into the
    patient-facing conversation context, so the bot has context if the patient
    replies. Creates the session if none exists yet.
    """
    store = SessionStore(redis_client=redis_client)
    office_id_str = str(office_id)
    session = await store.get_session(whatsapp_id, office_id_str)
    if session is None:
        session = SessionContext(
            conversation_id=conversation_id,
            office_id=office_id,
            whatsapp_id=whatsapp_id,
            patient_id=patient_id,
            status="active",
            claude_history=[],
            collected_data={},
        )
    session.claude_history.append({"role": "assistant", "content": content})
    session.last_message_at = datetime.utcnow().isoformat()
    await store.save_session(whatsapp_id, office_id_str, session)
