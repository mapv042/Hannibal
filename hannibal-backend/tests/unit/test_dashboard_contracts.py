"""The API shapes the dashboard reads: rows must serialise, secrets must not.

GET /api/patients answered 500 for any office with a patient (the response
schema named three columns differently from the model), and the dashboard
showed "Conecta tu Google Calendar" to connected offices (it read a token
field the office response never had). Both were contract mismatches no test
looked at.
"""

import uuid
from datetime import date, datetime, timezone

from app.db.models import Office, Patient
from app.modules.offices.schemas import OfficeResponse
from app.modules.patients.schemas import PatientResponse


def _patient(**overrides) -> Patient:
    fields = dict(
        id=uuid.uuid4(),
        office_id=uuid.uuid4(),
        name="Ana López",
        phone="5215512345678",
        whatsapp_id="5215512345678",
        is_active=True,
        total_appointments=0,
        created_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return Patient(**fields)


def test_patient_row_serialises_with_api_field_names():
    row = _patient(
        date_of_birth=date(1990, 5, 1),
        primary_reason="Revisión",
        how_they_found_us="Google",
    )
    body = PatientResponse.model_validate(row).model_dump()
    assert body["birth_date"] == date(1990, 5, 1)
    assert body["main_reason"] == "Revisión"
    assert body["how_found_us"] == "Google"


def test_patient_row_without_optional_data_serialises():
    body = PatientResponse.model_validate(_patient()).model_dump()
    assert body["birth_date"] is None
    assert body["main_reason"] is None


def _office(token) -> Office:
    return Office(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Consultorio",
        assistant_tone="formal",
        assistant_name="Sofía",
        assistant_gender="female",
        new_patient_duration_min=40,
        returning_patient_duration_min=30,
        is_active=True,
        onboarding_completed=True,
        notify_new_appointment=True,
        notify_cancellation=True,
        notify_new_patient=True,
        notify_unconfirmed=True,
        notify_arrival=True,
        notify_reschedule=True,
        plan="basic",
        google_calendar_token=token,
    )


def test_office_response_reports_calendar_link_without_the_token():
    body = OfficeResponse.model_validate(
        _office({"access_token": "secret", "refresh_token": "secret"})
    ).model_dump()
    assert body["google_calendar_connected"] is True
    assert "google_calendar_token" not in body
    assert "secret" not in str(body)


def test_office_response_without_calendar():
    body = OfficeResponse.model_validate(_office(None)).model_dump()
    assert body["google_calendar_connected"] is False
