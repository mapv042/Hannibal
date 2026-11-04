"""Offered slots as tappable options: markers, presentation, taps and validation."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.conversation import slot_options
from app.modules.conversation.base_manager import BaseToolConversationManager
from app.modules.conversation.grounding import Evidence, check_slot_markers
from app.modules.conversation.manager import ConversationManager
from app.modules.conversation.slot_options import present, slot_choice_text
from app.modules.conversation.state import OfferedSlot


def slot(slot_id, date_label, time_label):
    return OfferedSlot(slot_id=slot_id, date_label=date_label, time_label=time_label)


THU = "jueves 24 de septiembre"
FRI = "viernes 25 de septiembre"
OFFERED = [
    slot("2026-09-24T16:00", THU, "4:00 PM"),
    slot("2026-09-24T17:00", THU, "5:00 PM"),
    slot("2026-09-24T18:30", THU, "6:30 PM"),
    slot("2026-09-25T10:00", FRI, "10:00 AM"),
]


# ---------------------------------------------------------------- present()


def test_a_reply_without_markers_is_untouched():
    r = present("¿Para quién es la cita?", OFFERED)
    assert (r.kind, r.text, r.history_text) == ("text", "¿Para quién es la cita?", "¿Para quién es la cita?")


def test_three_slots_become_buttons_and_leave_the_text():
    r = present(
        "El jueves 24 de septiembre tengo estos horarios, ¿cuál te acomoda? "
        "[[2026-09-24T16:00]] [[2026-09-24T17:00]] [[2026-09-24T18:30]]",
        OFFERED,
    )
    assert r.kind == "buttons"
    assert r.text == "El jueves 24 de septiembre tengo estos horarios, ¿cuál te acomoda?"
    assert "PM" not in r.text  # the times are only on the buttons
    assert [b["title"] for b in r.buttons()] == ["Jue 24 · 4:00 PM", "Jue 24 · 5:00 PM", "Jue 24 · 6:30 PM"]
    assert r.buttons()[0]["id"] == "slot:2026-09-24T16:00"
    # The model remembers what it offered.
    assert "4:00 PM, 5:00 PM y 6:30 PM" in r.history_text


def test_four_slots_become_a_list_grouped_by_day():
    r = present(
        "Tengo estos horarios:\n- [[2026-09-24T16:00]]\n- [[2026-09-24T17:00]]\n"
        "- [[2026-09-24T18:30]]\n- [[2026-09-25T10:00]]\n\n¿Cuál prefieres?",
        OFFERED,
    )
    assert r.kind == "list"
    assert r.text == "Tengo estos horarios:\n\n¿Cuál prefieres?"
    assert r.sections() == [
        {"title": "Jueves 24 sep", "rows": [
            {"id": "slot:2026-09-24T16:00", "title": "4:00 PM"},
            {"id": "slot:2026-09-24T17:00", "title": "5:00 PM"},
            {"id": "slot:2026-09-24T18:30", "title": "6:30 PM"},
        ]},
        {"title": "Viernes 25 sep", "rows": [{"id": "slot:2026-09-25T10:00", "title": "10:00 AM"}]},
    ]
    assert f"{THU}: 4:00 PM, 5:00 PM y 6:30 PM; {FRI}: 10:00 AM" in r.history_text


def test_more_than_ten_slots_go_out_as_text():
    many = [slot(f"2026-09-24T{h:02d}:00", THU, f"{h - 12 if h > 12 else h}:00 {'PM' if h >= 12 else 'AM'}")
            for h in range(8, 19)]
    reply = "Tengo: " + " ".join(f"[[{s.slot_id}]]" for s in many)
    r = present(reply, many)
    assert r.kind == "text" and r.text == r.history_text
    assert "[[" not in r.text and "8:00 AM" in r.text


def test_a_marker_for_a_slot_no_tool_gave_is_dropped():
    r = present("Tengo [[2026-09-24T16:00]] [[2026-09-30T09:00]]", OFFERED)
    assert [s.slot_id for s in r.options] == ["2026-09-24T16:00"]
    assert "2026-09-30" not in r.text + r.history_text


def test_repeated_markers_offer_the_slot_once():
    r = present("[[2026-09-24T16:00]] [[2026-09-24T16:00]]", OFFERED)
    assert len(r.options) == 1


def test_markers_mid_sentence_leave_clean_punctuation():
    r = present("Tengo estos horarios: [[2026-09-24T16:00]], [[2026-09-24T17:00]].", OFFERED)
    assert r.text == "Tengo estos horarios:"


def test_only_markers_leave_an_empty_body():
    r = present("[[2026-09-24T16:00]]", OFFERED)
    assert r.kind == "buttons" and r.text == ""


# ---------------------------------------------------------------- taps


def test_slot_choice_text_carries_the_exact_slot_id():
    text = slot_choice_text("slot:2026-09-24T16:00", "Jue 24 · 4:00 PM")
    assert "slot_id 2026-09-24T16:00" in text
    assert "jueves 24 de septiembre" in text and "4:00 PM" in text


def test_other_button_ids_are_not_slot_choices():
    assert slot_choice_text("privacy_accept", "Acepto") is None
    assert slot_choice_text("slot:not-a-slot", "x") is None


class Extractor(BaseToolConversationManager):
    def __init__(self):
        pass


async def test_a_tapped_slot_reaches_the_model_with_its_id():
    out = await Extractor().extract_message(
        {
            "from": "5215550000001",
            "id": "wamid.1",
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "slot:2026-09-24T17:00", "title": "5:00 PM"},
            },
        },
        office=None,
    )
    assert "slot_id 2026-09-24T17:00" in out["text"]


async def test_other_taps_still_read_as_their_title():
    out = await Extractor().extract_message(
        {
            "from": "5215550000001",
            "id": "wamid.1",
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": "privacy_accept", "title": "Acepto"}},
        },
        office=None,
    )
    assert out["text"] == "Acepto"


# ---------------------------------------------------------------- validator


def evidence(markers=True):
    return Evidence(
        today=date(2026, 9, 21),
        slot_markers=markers,
        offered_slot_ids={s.slot_id for s in OFFERED},
    )


def test_unknown_marker_is_flagged():
    v = check_slot_markers("Tengo [[2026-09-30T09:00]]", evidence())
    assert v and v[0].kind == "slot_marker" and "2026-09-30T09:00" in v[0].detail


def test_known_markers_pass():
    assert check_slot_markers("Tengo estos horarios: [[2026-09-24T16:00]]", evidence()) == []


def test_announcing_slots_and_giving_none_is_flagged():
    v = check_slot_markers("El jueves tengo estos horarios, ¿cuál te acomoda?", evidence())
    assert v and v[0].kind == "slot_marker"


def test_announcing_slots_written_as_times_passes():
    assert check_slot_markers("Tengo estos horarios: 4:00 PM y 5:00 PM", evidence()) == []


def test_the_doctor_flow_is_not_checked():
    assert check_slot_markers("Tengo estos horarios, ¿cuál?", evidence(markers=False)) == []


# ---------------------------------------------------------------- sending


class Client:
    def __init__(self, fail_interactive=False):
        self.sent, self.fail_interactive = [], fail_interactive

    async def send_text_message(self, **kw):
        self.sent.append(("text", kw))
        return "wamid.text"

    async def send_interactive_buttons(self, **kw):
        if self.fail_interactive:
            raise RuntimeError("refused")
        self.sent.append(("buttons", kw))
        return "wamid.buttons"

    async def send_interactive_list(self, **kw):
        if self.fail_interactive:
            raise RuntimeError("refused")
        self.sent.append(("list", kw))
        return "wamid.list"


def manager(client):
    m = ConversationManager.__new__(ConversationManager)
    m.meta_client = client
    return m


OFFICE = SimpleNamespace(id="office-1", whatsapp_phone_id="pnid", whatsapp_token="tok")


async def test_buttons_go_out_with_the_text_as_body():
    client = Client()
    reply = present("¿Cuál te acomoda? [[2026-09-24T16:00]] [[2026-09-24T17:00]]", OFFERED)
    assert await manager(client)._send_reply(OFFICE, "521555", reply) == "wamid.buttons"
    kind, kw = client.sent[0]
    assert kind == "buttons" and kw["body_text"] == "¿Cuál te acomoda?" and len(kw["buttons"]) == 2


async def test_a_list_goes_out_behind_ver_horarios():
    client = Client()
    reply = present("Tengo: " + " ".join(f"[[{s.slot_id}]]" for s in OFFERED), OFFERED)
    await manager(client)._send_reply(OFFICE, "521555", reply)
    kind, kw = client.sent[0]
    assert kind == "list" and kw["button_text"] == "Ver horarios"


async def test_a_reply_too_long_for_a_body_goes_first_as_text():
    client = Client()
    reply = present("x" * 1100 + " [[2026-09-24T16:00]]", OFFERED)
    await manager(client)._send_reply(OFFICE, "521555", reply)
    assert [k for k, _ in client.sent] == ["text", "buttons"]
    assert client.sent[1][1]["body_text"] == slot_options.SHORT_BODY


async def test_an_empty_body_gets_the_short_prompt():
    client = Client()
    await manager(client)._send_reply(OFFICE, "521555", present("[[2026-09-24T16:00]]", OFFERED))
    assert client.sent[0][1]["body_text"] == slot_options.SHORT_BODY


async def test_refused_buttons_fall_back_to_the_slots_in_words():
    client = Client(fail_interactive=True)
    reply = present("¿Cuál te acomoda? [[2026-09-24T16:00]] [[2026-09-24T17:00]]", OFFERED)
    await manager(client)._send_reply(OFFICE, "521555", reply)
    kind, kw = client.sent[0]
    assert kind == "text" and "4:00 PM y 5:00 PM" in kw["text"]


async def test_plain_replies_stay_plain():
    client = Client()
    await manager(client)._send_reply(OFFICE, "521555", present("Hola", OFFERED))
    assert client.sent == [("text", {"phone_number_id": "pnid", "token": "tok", "to": "521555", "text": "Hola"})]


@pytest.mark.parametrize("weekday_slot, title", [
    ("2026-09-30T12:30", "Mié 30 · 12:30 PM"),
    ("2026-09-26T09:00", "Sáb 26 · 9:00 AM"),
])
def test_button_titles_fit_twenty_characters(weekday_slot, title):
    label = title.split(" · ")[1]
    t = slot_options.button_title(slot(weekday_slot, "x", label))
    assert t == title and len(t) <= 20
