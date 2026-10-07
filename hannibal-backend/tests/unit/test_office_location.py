"""Reminders say where the cita is, not just the practice's name.

The address was required in onboarding but never reached a reminder: a
patient reading "tu cita en Consultorio Demo" still had to ask where that is.
It rides in the `location` param the approved Meta templates already have.
"""

from types import SimpleNamespace

from app.modules.reminders.templates import office_location, reminder_day_before


def test_name_and_address_on_one_line():
    office = SimpleNamespace(name="Consultorio Demo", address="Av. Insurgentes Sur 1234, Del Valle")
    location = office_location(office)
    assert location == "Consultorio Demo, Av. Insurgentes Sur 1234, Del Valle"
    assert "\n" not in location  # Meta rejects newlines in template params


def test_without_address_falls_back_to_the_name():
    assert office_location(SimpleNamespace(name="Consultorio Demo", address=None)) == "Consultorio Demo"
    assert office_location(SimpleNamespace(name="Consultorio Demo", address="  ")) == "Consultorio Demo"


def test_reminder_text_carries_the_address():
    office = SimpleNamespace(name="Consultorio Demo", address="Av. Insurgentes Sur 1234")
    text = reminder_day_before(
        {"patient_name": "Ana", "time": "10:00 AM", "date": "mañana",
         "office_name": office_location(office), "assistant_name": "Sofía"},
        tone="informal",
    )
    assert "Av. Insurgentes Sur 1234" in text
