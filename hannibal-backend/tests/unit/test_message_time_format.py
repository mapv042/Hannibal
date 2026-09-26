"""Every automatic message writes times the way the bot does: 12-hour, month names."""

from datetime import datetime, timezone

import pytest

from app.core.constants import MX_TIMEZONE

AFTERNOON = datetime(2026, 10, 1, 16, 50, tzinfo=MX_TIMEZONE)
EXPECTED = "jueves 1 de octubre a las 4:50 PM"


@pytest.mark.parametrize("formatter", [
    "app.modules.notifications.templates:format_slot",
    "app.modules.audit.templates:format_slot",
    "app.modules.scheduling.reschedule_notify:_format_slot",
    "app.modules.urgencies.templates:format_datetime",
    "app.modules.ai.tool_helpers:format_appointment_dt",
])
def test_slot_formatters_agree(formatter):
    import importlib

    module, name = formatter.split(":")
    fn = getattr(importlib.import_module(module), name)
    assert fn(AFTERNOON) == EXPECTED
    # Same instant given in UTC: still Mexico City wall time.
    assert fn(AFTERNOON.astimezone(timezone.utc)) == EXPECTED


def test_no_24h_times_in_human_facing_modules():
    """A guard against regressions: human-facing modules don't print %H:%M."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "modules"
    human_facing = [
        "reminders/tasks.py", "reminders/templates.py", "notifications/templates.py",
        "notifications/service.py", "urgencies/templates.py", "audit/templates.py",
        "audit/service.py", "scheduling/reschedule_notify.py", "scheduling/waiting_room.py",
        "scheduling/patient_notify.py",
    ]
    offenders = [
        f for f in human_facing
        if "strftime(\"%H:%M\")" in (root / f).read_text()
        or "strftime('%H:%M')" in (root / f).read_text()
    ]
    assert offenders == []
