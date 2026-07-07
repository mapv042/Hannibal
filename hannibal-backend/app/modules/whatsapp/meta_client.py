"""Meta Cloud API client for WhatsApp messaging."""

from __future__ import annotations

import asyncio
from typing import Optional, List, Any, Dict
import json

import httpx

from app.utils.logger import get_logger
from app.core.exceptions import WhatsAppError

logger = get_logger(__name__)

BASE_URL = "https://graph.facebook.com/v21.0"

# Transient failures worth retrying; other 4xx are permanent (bad token,
# invalid recipient, malformed template) and retrying only adds latency.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
SEND_MAX_ATTEMPTS = 3
SEND_BACKOFF_SECONDS = 1.0


class MetaCloudClient:
    """
    Async HTTP client for Meta Cloud API (WhatsApp Business Account).

    Handles all interactions with Meta's Graph API for sending messages,
    managing media, marking messages as read, etc.
    """

    def __init__(self, timeout: int = 30):
        """
        Initialize Meta Cloud API client.

        Args:
            timeout: HTTP request timeout in seconds
        """
        self.timeout = timeout

    async def _post_with_retries(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        *,
        log_event: str,
        log_context: Dict[str, Any],
    ) -> httpx.Response:
        """POST with retries on transient failures (network errors, 429/5xx).

        Exponential backoff between attempts. Non-retryable 4xx responses and
        exhausted retries surface as httpx errors for the caller to wrap in
        WhatsAppError, preserving the existing error contract.
        """
        delay = SEND_BACKOFF_SECONDS
        for attempt in range(1, SEND_MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
            except httpx.TransportError as e:
                if attempt < SEND_MAX_ATTEMPTS:
                    logger.warning(
                        f"{log_event}_retrying",
                        attempt=attempt,
                        error=str(e),
                        **log_context,
                    )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise

            if (
                response.status_code in RETRYABLE_STATUS_CODES
                and attempt < SEND_MAX_ATTEMPTS
            ):
                logger.warning(
                    f"{log_event}_retrying",
                    attempt=attempt,
                    status_code=response.status_code,
                    **log_context,
                )
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if response.status_code >= 400:
                logger.error(
                    f"{log_event}_meta_error",
                    status_code=response.status_code,
                    response_body=response.text,
                    **log_context,
                )
            response.raise_for_status()
            return response

        raise WhatsAppError("Unreachable retry state")  # pragma: no cover

    async def send_text_message(
        self,
        phone_number_id: str,
        token: str,
        to: str,
        text: str,
    ) -> str:
        """
        Send a text message via WhatsApp.

        Args:
            phone_number_id: WhatsApp Business Account phone number ID
            token: Access token for authentication
            to: Recipient's WhatsApp ID (phone number with country code, no +)
            text: Message text to send

        Returns:
            Message ID from Meta

        Raises:
            WhatsAppError: If API call fails
        """
        url = f"{BASE_URL}/{phone_number_id}/messages"

        # Normalize Mexican mobile numbers: WhatsApp sends 521XXXXXXXXXX
        # but Meta API expects 52XXXXXXXXXX (without the extra 1)
        normalized_to = to
        if to.startswith("521") and len(to) == 13:
            normalized_to = "52" + to[3:]

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._post_with_retries(
                url,
                payload,
                headers,
                log_event="send_text_message",
                log_context={"to": to, "phone_number_id": phone_number_id},
            )
        except httpx.HTTPError as e:
            logger.error(
                "send_text_message_failed",
                to=to,
                phone_number_id=phone_number_id,
                error=str(e),
            )
            raise WhatsAppError(f"Failed to send text message: {str(e)}") from e

        data = response.json()
        message_id = data.get("messages", [{}])[0].get("id")

        if not message_id:
            logger.error("send_text_message_no_id", response=data)
            raise WhatsAppError("No message ID returned by Meta")

        logger.info(
            "send_text_message_success",
            message_id=message_id,
            to=to,
        )

        return message_id

    async def send_template_message(
        self,
        phone_number_id: str,
        token: str,
        to: str,
        template_name: str,
        params: Optional[List[Dict[str, str]]] = None,
        language_code: str = "es",
    ) -> str:
        """
        Send a pre-approved template message.

        Args:
            phone_number_id: WhatsApp Business Account phone number ID
            token: Access token for authentication
            to: Recipient's WhatsApp ID
            template_name: Name of the approved template
            params: List of parameter objects with "type": "text" and "text": "value"
            language_code: Template language code (default: "es")

        Returns:
            Message ID from Meta

        Raises:
            WhatsAppError: If API call fails
        """
        url = f"{BASE_URL}/{phone_number_id}/messages"

        # Normalize Mexican mobile numbers: WhatsApp sends 521XXXXXXXXXX
        # but Meta API expects 52XXXXXXXXXX (without the extra 1)
        normalized_to = to
        if to.startswith("521") and len(to) == 13:
            normalized_to = "52" + to[3:]

        template_object = {
            "name": template_name,
            "language": {"code": language_code},
        }

        if params:
            template_object["components"] = [
                {
                    "type": "body",
                    "parameters": params,
                }
            ]

        payload = {
            "messaging_product": "whatsapp",
            "to": normalized_to,
            "type": "template",
            "template": template_object,
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._post_with_retries(
                url,
                payload,
                headers,
                log_event="send_template_message",
                log_context={
                    "to": to,
                    "template_name": template_name,
                    "phone_number_id": phone_number_id,
                },
            )
        except httpx.HTTPError as e:
            logger.error(
                "send_template_message_failed",
                to=to,
                template_name=template_name,
                phone_number_id=phone_number_id,
                error=str(e),
            )
            raise WhatsAppError(f"Failed to send template message: {str(e)}") from e

        data = response.json()
        message_id = data.get("messages", [{}])[0].get("id")

        if not message_id:
            logger.error("send_template_message_no_id", response=data)
            raise WhatsAppError("No message ID returned by Meta")

        logger.info(
            "send_template_message_success",
            message_id=message_id,
            to=to,
            template_name=template_name,
        )

        return message_id

    async def mark_as_read(
        self,
        phone_number_id: str,
        token: str,
        message_id: str,
    ) -> bool:
        """
        Mark a received message as read.

        Args:
            phone_number_id: WhatsApp Business Account phone number ID
            token: Access token for authentication
            message_id: ID of the message to mark as read

        Returns:
            True if successful

        Raises:
            WhatsAppError: If API call fails
        """
        url = f"{BASE_URL}/{message_id}"

        payload = {
            "status": "read",
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(
                "mark_as_read_failed",
                message_id=message_id,
                phone_number_id=phone_number_id,
                error=str(e),
            )
            raise WhatsAppError(f"Failed to mark message as read: {str(e)}") from e

        logger.info(
            "mark_as_read_success",
            message_id=message_id,
        )

        return True

    async def get_media_url(
        self,
        phone_number_id: str,
        token: str,
        media_id: str,
    ) -> str:
        """
        Get the download URL for media from a message.

        Args:
            phone_number_id: WhatsApp Business Account phone number ID
            token: Access token for authentication
            media_id: ID of the media object

        Returns:
            Download URL for the media

        Raises:
            WhatsAppError: If API call fails
        """
        url = f"{BASE_URL}/{media_id}"

        headers = {
            "Authorization": f"Bearer {token}",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    url,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(
                "get_media_url_failed",
                media_id=media_id,
                phone_number_id=phone_number_id,
                error=str(e),
            )
            raise WhatsAppError(f"Failed to get media URL: {str(e)}") from e

        data = response.json()
        media_url = data.get("url")

        if not media_url:
            logger.error("get_media_url_no_url", response=data)
            raise WhatsAppError("No media URL returned by Meta")

        logger.info(
            "get_media_url_success",
            media_id=media_id,
        )

        return media_url

    async def download_media(
        self,
        media_url: str,
        token: str,
    ) -> bytes:
        """
        Download media content from Meta servers.

        Args:
            media_url: The download URL from get_media_url()
            token: Access token for authentication

        Returns:
            Media bytes content

        Raises:
            WhatsAppError: If download fails
        """
        headers = {
            "Authorization": f"Bearer {token}",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    media_url,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(
                "download_media_failed",
                media_url=media_url,
                error=str(e),
            )
            raise WhatsAppError(f"Failed to download media: {str(e)}") from e

        logger.info(
            "download_media_success",
            size=len(response.content),
        )

        return response.content

    async def upload_media(
        self,
        phone_number_id: str,
        token: str,
        file_content: bytes,
        file_type: str,
        filename: Optional[str] = None,
    ) -> str:
        """
        Upload media to Meta servers for sending.

        Args:
            phone_number_id: WhatsApp Business Account phone number ID
            token: Access token for authentication
            file_content: Raw file bytes to upload
            file_type: MIME type (e.g., "image/jpeg", "application/pdf")
            filename: Optional filename for the media

        Returns:
            Media ID from Meta

        Raises:
            WhatsAppError: If upload fails
        """
        url = f"{BASE_URL}/{phone_number_id}/media"

        headers = {
            "Authorization": f"Bearer {token}",
        }

        files = {
            "file": (filename or "file", file_content, file_type),
            "type": (None, file_type),
            "messaging_product": (None, "whatsapp"),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    files=files,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(
                "upload_media_failed",
                phone_number_id=phone_number_id,
                file_type=file_type,
                error=str(e),
            )
            raise WhatsAppError(f"Failed to upload media: {str(e)}") from e

        data = response.json()
        media_id = data.get("id")

        if not media_id:
            logger.error("upload_media_no_id", response=data)
            raise WhatsAppError("No media ID returned by Meta")

        logger.info(
            "upload_media_success",
            media_id=media_id,
            file_type=file_type,
        )

        return media_id
