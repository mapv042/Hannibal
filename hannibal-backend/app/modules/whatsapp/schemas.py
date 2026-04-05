"""Pydantic schemas for WhatsApp webhook and API interactions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, List

from pydantic import BaseModel, Field


class WhatsAppTextMessage(BaseModel):
    """WhatsApp text message body."""

    body: str = Field(..., description="Message text content")


class WhatsAppMediaMessage(BaseModel):
    """WhatsApp media message (image, video, audio, file)."""

    id: str = Field(..., description="Media object ID")
    mime_type: Optional[str] = Field(None, description="MIME type of media")
    sha256: Optional[str] = Field(None, description="SHA256 hash of media")


class WhatsAppMessage(BaseModel):
    """Individual WhatsApp message."""

    id: str = Field(..., description="Unique message ID from Meta")
    from_: str = Field(..., alias="from", description="Sender's WhatsApp ID (phone number)")
    timestamp: int = Field(..., description="Unix timestamp of message")
    type: str = Field(..., description="Message type: text, image, video, audio, file, location, contacts, etc.")
    text: Optional[WhatsAppTextMessage] = Field(None, description="Text message body")
    image: Optional[WhatsAppMediaMessage] = Field(None, description="Image media object")
    video: Optional[WhatsAppMediaMessage] = Field(None, description="Video media object")
    audio: Optional[WhatsAppMediaMessage] = Field(None, description="Audio media object")
    document: Optional[WhatsAppMediaMessage] = Field(None, description="Document media object")
    location: Optional[dict] = Field(None, description="Location data")
    contacts: Optional[List[dict]] = Field(None, description="Contact information")
    referral: Optional[dict] = Field(None, description="Referral information")

    class Config:
        populate_by_name = True


class WhatsAppStatus(BaseModel):
    """WhatsApp delivery status update."""

    id: str = Field(..., description="Message ID")
    status: str = Field(..., description="Status: sent, delivered, read, failed")
    timestamp: int = Field(..., description="Unix timestamp")
    recipient_id: str = Field(..., description="Recipient WhatsApp ID")
    errors: Optional[List[dict]] = Field(None, description="Error details if status is failed")


class WhatsAppEntry(BaseModel):
    """Entry in the webhook payload containing changes."""

    id: str = Field(..., description="Entry ID (phone_number_id)")
    changes: List[dict] = Field(..., description="List of changes")


class WhatsAppWebhookPayload(BaseModel):
    """Meta Cloud API webhook payload structure."""

    object: str = Field(..., description="Webhook object type, always 'whatsapp_business_account'")
    entry: List[dict] = Field(..., description="Array of entry objects")


class SendMessageRequest(BaseModel):
    """Request to send a message via WhatsApp."""

    to: str = Field(..., description="Recipient WhatsApp ID (phone number)")
    text: str = Field(..., description="Message text to send")
    message_type: str = Field(default="text", description="Type of message: text, template, media")


class SendTemplateMessageRequest(BaseModel):
    """Request to send a template message."""

    to: str = Field(..., description="Recipient WhatsApp ID (phone number)")
    template_name: str = Field(..., description="Name of the template")
    template_language_code: str = Field(default="es", description="Template language code")
    template_parameters: Optional[List[dict]] = Field(None, description="Template parameters")


class SendMessageResponse(BaseModel):
    """Response after sending a message."""

    message_id: str = Field(..., description="Unique message ID returned by Meta")
    status: str = Field(default="sent", description="Message status")
    timestamp: Optional[int] = Field(None, description="Unix timestamp of sending")


class WhatsAppStatusPayload(BaseModel):
    """Webhook payload for status updates."""

    messaging_product: str = Field(default="whatsapp", description="Always 'whatsapp'")
    recipient_status_update_json: Optional[str] = Field(None, description="Status update JSON")


class WebhookVerificationRequest(BaseModel):
    """Webhook verification request from Meta."""

    hub_mode: str = Field(..., alias="hub.mode", description="Should be 'subscribe'")
    hub_challenge: str = Field(..., alias="hub.challenge", description="Challenge string to echo back")
    hub_verify_token: str = Field(..., alias="hub.verify_token", description="Verification token from config")

    class Config:
        populate_by_name = True
