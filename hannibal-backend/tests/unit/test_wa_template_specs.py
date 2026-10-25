"""The template catalogue is what gets created on every doctor's WABA.

A spec whose body names a variable its sender never fills (or vice versa) is
approved by Meta and then fails on every send; a body Meta rejects leaves that
message impossible outside the 24h window. Both are caught here, not in prod.
"""

import re

import pytest

from app.modules.reminders import wa_templates as wt
from app.modules.whatsapp.template_provisioning import build_create_payload

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

# Every sender builds its params through one of these; the spec must name the
# same variables.
BUILDERS = {
    wt.TEMPLATE_OFFICE_MESSAGE: lambda: wt.build_office_message_params("a", "b", "c"),
    wt.TEMPLATE_FOLLOW_UP: lambda: wt.build_follow_up_params("a", "b"),
    wt.TEMPLATE_CONFIRMATION_DAY_BEFORE: lambda: wt.build_confirmation_params("a", "b", "c", "d"),
    wt.TEMPLATE_REMINDER: lambda: wt.build_reminder_params("a", "b", "c", "d"),
    wt.TEMPLATE_ARRIVAL_CHECK_IN: lambda: wt.build_arrival_check_params("a", "b"),
    wt.TEMPLATE_URGENCY_ALERT: lambda: wt.build_urgency_alert_params("a"),
    wt.TEMPLATE_RESCHEDULE_NOTICE: lambda: wt.build_reschedule_notice_params("a", "b"),
    wt.TEMPLATE_DOCTOR_NEW_APPOINTMENT: lambda: wt.build_doctor_new_appointment_params("a", "b"),
    wt.TEMPLATE_DOCTOR_NEW_PATIENT_APPOINTMENT: lambda: wt.build_doctor_new_patient_appointment_params("a", "b"),
    wt.TEMPLATE_DOCTOR_CANCELLATION: lambda: wt.build_doctor_cancellation_params("a", "b"),
    wt.TEMPLATE_DOCTOR_NEW_PATIENT: lambda: wt.build_doctor_new_patient_params("a"),
    wt.TEMPLATE_DOCTOR_DAILY_AGENDA: lambda: wt.build_doctor_daily_agenda_params("a", "b"),
    wt.TEMPLATE_DOCTOR_PATIENT_ARRIVED: lambda: wt.build_doctor_patient_arrived_params("a", "b"),
    wt.TEMPLATE_DOCTOR_PATIENT_DELAYED: lambda: wt.build_doctor_patient_delayed_params("a", "b"),
    wt.TEMPLATE_DOCTOR_PATIENT_NO_RESPONSE: lambda: wt.build_doctor_patient_no_response_params("a", "b"),
    wt.TEMPLATE_DOCTOR_PATIENT_NOSHOW_CANCEL: lambda: wt.build_doctor_patient_noshow_cancel_params("a", "b"),
    wt.TEMPLATE_DOCTOR_SYNC_WARNING: lambda: wt.build_doctor_sync_warning_params("a", "b"),
    wt.TEMPLATE_DOCTOR_APPOINTMENT_BRIEF: lambda: wt.build_doctor_appointment_brief_params("a", "b"),
    wt.TEMPLATE_DOCTOR_CALENDAR_DISCONNECTED: lambda: wt.build_doctor_calendar_disconnected_params("a"),
    wt.TEMPLATE_DOCTOR_CALENDAR_CHANGE: lambda: wt.build_doctor_calendar_change_params("a", "b"),
}

SPECS = {spec.name: spec for spec in wt.TEMPLATE_SPECS}


def test_every_template_constant_has_exactly_one_spec():
    constants = {v for k, v in vars(wt).items() if k.startswith("TEMPLATE_") and k not in (
        "TEMPLATE_LANGUAGE", "TEMPLATE_SPECS", "TEMPLATE_NAME_PREFIX"
    )}
    assert constants == set(SPECS)
    assert len(SPECS) == len(wt.TEMPLATE_SPECS)  # no duplicate names
    assert set(BUILDERS) == set(SPECS)


@pytest.mark.parametrize("name", sorted(SPECS))
def test_spec_variables_match_its_sender(name):
    spec = SPECS[name]
    in_body = PLACEHOLDER.findall(spec.body)
    sent = [p["parameter_name"] for p in BUILDERS[name]()]
    assert sorted(in_body) == sorted(sent)
    assert set(spec.examples) == set(in_body)


@pytest.mark.parametrize("name", sorted(SPECS))
def test_spec_body_follows_meta_rules(name):
    body = SPECS[name].body
    assert not body.strip().startswith("{{") and not body.strip().endswith("}}")
    assert not re.search(r"\}\}\s*\{\{", body), "adjacent variables"
    assert "\n" not in body and len(body) <= 1024
    assert re.fullmatch(r"[a-z0-9_]+", name)
    for title in SPECS[name].quick_replies:
        assert len(title) <= 25


def test_every_name_carries_the_catalogue_prefix_and_no_suffix():
    assert all(name.startswith(wt.TEMPLATE_NAME_PREFIX) for name in SPECS)
    assert not [name for name in SPECS if re.search(r"_v\d+$", name)]


def test_create_payload_uses_named_params_and_quick_replies():
    payload = build_create_payload(SPECS[wt.TEMPLATE_CONFIRMATION_DAY_BEFORE])
    assert payload["parameter_format"] == "named"
    assert payload["language"] == wt.TEMPLATE_LANGUAGE
    body, buttons = payload["components"]
    assert {p["param_name"] for p in body["example"]["body_text_named_params"]} == {
        "patient_name", "location", "appointment_date", "appointment_time"
    }
    assert [b["text"] for b in buttons["buttons"]] == ["Confirmar", "Cancelar", "Reagendar"]


def test_params_fold_line_breaks_meta_would_reject():
    (_, _, text) = wt.build_office_message_params("Ana", "Consultorio", "Hola.\n\nSu cita\tcambió.     Gracias")
    assert text["text"] == "Hola. Su cita cambió. Gracias"
