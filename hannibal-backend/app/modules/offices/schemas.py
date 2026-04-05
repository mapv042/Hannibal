"""Pydantic schemas for office CRUD operations."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CreateOfficeRequest(BaseModel):
    """Request to create a new office."""

    name: str = Field(..., description="Office name", max_length=255)
    specialty: Optional[str] = Field(
        None, description="Medical specialty", max_length=255
    )
    whatsapp_phone: Optional[str] = Field(
        None, description="WhatsApp phone number", max_length=20
    )
    city: Optional[str] = Field(None, description="City", max_length=100)
    address: Optional[str] = Field(None, description="Address", max_length=500)


class UpdateOfficeRequest(BaseModel):
    """Request to update an office."""

    name: Optional[str] = Field(None, description="Office name", max_length=255)
    specialty: Optional[str] = Field(
        None, description="Medical specialty", max_length=255
    )
    whatsapp_phone: Optional[str] = Field(
        None, description="WhatsApp phone number", max_length=20
    )
    city: Optional[str] = Field(None, description="City", max_length=100)
    address: Optional[str] = Field(None, description="Address", max_length=500)
    assistant_tone: Optional[str] = Field(
        None, description="Assistant tone (formal|informal)"
    )
    assistant_name: Optional[str] = Field(None, description="Assistant name")
    is_active: Optional[bool] = Field(None, description="Is active")


class OfficeResponse(BaseModel):
    """Response model for office data."""

    id: UUID
    user_id: UUID
    name: str
    specialty: Optional[str]
    whatsapp_phone: Optional[str]
    city: Optional[str]
    address: Optional[str]
    assistant_tone: str
    assistant_name: str
    is_active: bool
    plan: str

    class Config:
        from_attributes = True
