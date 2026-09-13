"""Read-only catalogues the onboarding wizard offers the doctor.

Served from the backend rather than duplicated in the frontend so the
suggestions the doctor picks from and the labels the assistant later says to
patients can never drift apart.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.catalogs import (
    INSURERS,
    INTAKE_QUESTIONS,
    SPECIALTIES,
    services_for,
    symptoms_for,
)

router = APIRouter()


@router.get("/specialties")
async def list_specialties() -> dict:
    """Selectable specialties. `otra` keeps the free-text escape hatch."""
    return {"specialties": SPECIALTIES}


@router.get("/insurers")
async def list_insurers() -> dict:
    """Major Mexican insurers under their official names."""
    return {"insurers": INSURERS}


@router.get("/intake-questions")
async def list_intake_questions() -> dict:
    """Questions the assistant can gather before a visit."""
    return {"questions": INTAKE_QUESTIONS}


@router.get("/by-specialty")
async def catalogs_by_specialty(
    specialty: str | None = Query(None, description="Specialty id"),
) -> dict:
    """Suggested services and alarm symptoms for one specialty.

    Both fall back to the generic lists for an unknown or custom specialty, so
    the wizard never presents the doctor with an empty screen.
    """
    return {
        "specialty": specialty,
        "services": services_for(specialty),
        "emergency_symptoms": symptoms_for(specialty),
    }
