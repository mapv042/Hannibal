"""Date labels and the generated capabilities section."""

from datetime import date, datetime
from types import SimpleNamespace

from app.modules.ai.prompts.base import _offset_phrase, build_capabilities_section
from app.modules.ai.tool_helpers import format_appointment_dt, parse_slot_id, slot_id_for
from app.core.constants import MX_TIMEZONE
from app.utils.dates import build_date_reference_block, long_date_label, time_label


def test_long_date_label():
    assert long_date_label(date(2026, 9, 24), date(2026, 9, 23)) == "jueves 24 de septiembre"
    assert long_date_label(date(2027, 1, 5), date(2026, 9, 23)) == "martes 5 de enero de 2027"


def test_time_label_12h():
    assert time_label(datetime(2026, 1, 1, 16, 0)) == "4:00 PM"
    assert time_label(datetime(2026, 1, 1, 0, 30)) == "12:30 AM"
    assert time_label(datetime(2026, 1, 1, 12, 5)) == "12:05 PM"


def test_format_appointment_dt():
    dt = datetime(2026, 9, 24, 16, 0, tzinfo=MX_TIMEZONE)
    assert format_appointment_dt(dt).endswith("24 de septiembre a las 4:00 PM")


def test_slot_id_round_trip():
    dt = datetime(2026, 9, 24, 16, 0, tzinfo=MX_TIMEZONE)
    assert parse_slot_id(slot_id_for(dt)) == dt
    assert "error" in parse_slot_id("jueves a las 4")


def test_reference_block_maps_labels_to_iso():
    block = build_date_reference_block(datetime(2026, 9, 23, 20, 53, tzinfo=MX_TIMEZONE))
    assert "mañana: jueves 24 de septiembre = 2026-09-24" in block
    assert "8:53 PM" in block


def test_offset_phrases():
    assert _offset_phrase(-10080) == "7 días antes"
    assert _offset_phrase(-1440) == "1 día antes"
    assert _offset_phrase(-360) == "6 horas antes"
    assert _offset_phrase(0) == "a la hora de la cita"
    assert _offset_phrase(120) == "2 horas después"


def rule(t, o, enabled=True):
    return SimpleNamespace(reminder_type=t, offset_minutes=o, enabled=enabled)


def test_capabilities_list_only_enabled_patient_reminders():
    section = build_capabilities_section([
        rule("week_before", -10080, enabled=False),
        rule("day_before", -1440),
        rule("doctor_brief", -15),
    ])
    assert "1 día antes" in section
    assert "7 días antes" not in section
    assert "15 minutos" not in section  # doctor-facing


def test_capabilities_without_reminders_says_so():
    assert "no tiene recordatorios" in build_capabilities_section([])


def sched(dow, start, end):
    from datetime import time
    return SimpleNamespace(day_of_week=dow, start_time=time(*start), end_time=time(*end), is_active=True)


def test_schedule_section_groups_identical_days():
    from app.modules.ai.prompts.base import build_schedule_section

    rows = []
    for dow in (1, 2, 3, 4, 5):
        rows += [sched(dow, (9, 0), (14, 0)), sched(dow, (16, 0), (19, 0))]
    rows.append(sched(6, (9, 0), (13, 0)))
    section = build_schedule_section(rows)
    assert "- Lunes a viernes: 9:00 AM a 2:00 PM y 4:00 PM a 7:00 PM" in section
    assert "- Sábado: 9:00 AM a 1:00 PM" in section
    assert "domingo" not in section.lower()


def test_schedule_section_empty_without_rows():
    from app.modules.ai.prompts.base import build_schedule_section

    assert build_schedule_section([]) == ""
