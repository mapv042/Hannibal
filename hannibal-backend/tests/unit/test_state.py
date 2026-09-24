"""ConversationState: the working memory rendered into every turn."""

from datetime import datetime

from app.core.constants import MX_TIMEZONE
from app.modules.conversation.state import (
    MAX_OFFERED_SLOTS,
    MAX_RECENT_ACTIONS,
    BookingDraft,
    ConversationState,
    OfferedSlot,
)


def slot(sid, date_label="jueves 24 de septiembre", time_label="4:00 PM"):
    return OfferedSlot(slot_id=sid, date_label=date_label, time_label=time_label)


def test_empty_state_renders_nothing():
    assert ConversationState().render() == ""


def test_slots_are_deduped_and_capped():
    st = ConversationState()
    st.remember_slots([slot(f"2026-09-24T{h:02d}:00") for h in range(8, 20)])
    st.remember_slots([slot("2026-09-24T08:00")])
    assert len({s.slot_id for s in st.offered_slots}) == len(st.offered_slots)
    st.remember_slots([slot(f"2026-10-{d:02d}T10:00") for d in range(1, 31)])
    assert len(st.offered_slots) == MAX_OFFERED_SLOTS


def test_render_shows_slot_ids_verbatim():
    st = ConversationState()
    st.remember_slots([slot("2026-09-24T16:00")])
    assert "4:00 PM [2026-09-24T16:00]" in st.render()


def test_draft_is_marked_as_not_booked():
    st = ConversationState()
    st.draft = BookingDraft(
        slot_id="2026-09-24T16:00", label="x", summary="Cita para Ana", patient_name="Ana",
        reason="revisión", created_at="now",
    )
    assert "todavía NO está agendada" in st.render()


def test_actions_are_capped_and_back_claims_only_when_ok():
    st = ConversationState()
    now = datetime(2026, 9, 23, 10, tzinfo=MX_TIMEZONE)
    st.record_action("cancel_appointment", False, "falló", [], now)
    assert st.successful_claims() == set()
    for i in range(MAX_RECENT_ACTIONS + 3):
        st.record_action("confirm_booking", True, f"ok {i}", ["book"], now)
    assert len(st.recent_actions) == MAX_RECENT_ACTIONS
    assert st.successful_claims() == {"book"}


def test_drop_past_slots():
    st = ConversationState()
    st.remember_slots([slot("2026-09-23T09:00"), slot("2026-09-23T18:00")])
    st.drop_past_slots(datetime(2026, 9, 23, 12, tzinfo=MX_TIMEZONE))
    assert [s.slot_id for s in st.offered_slots] == ["2026-09-23T18:00"]


def test_round_trips_through_json():
    st = ConversationState()
    st.remember_slots([slot("2026-09-24T16:00")])
    assert ConversationState.model_validate_json(st.model_dump_json()) == st
