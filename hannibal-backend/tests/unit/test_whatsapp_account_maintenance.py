"""Token refresh and template provisioning for an office's WhatsApp account.

Meta is faked at the function seam (inspect/refresh/list/create); what is under
test is the decision each makes and what ends up stored on the office.
"""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.exceptions import WhatsAppError
from app.modules.reminders.wa_templates import TEMPLATE_SPECS
from app.modules.whatsapp import template_provisioning as tp
from app.modules.whatsapp import token_lifecycle as tl
from app.utils.dates import real_now


class FakeDB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def make_office(**overrides):
    fields = dict(
        id=uuid.uuid4(),
        whatsapp_token="old-token",
        whatsapp_waba_id="waba-1",
        whatsapp_token_expires_at=None,
        whatsapp_token_checked_at=None,
        whatsapp_token_error=None,
        whatsapp_templates=None,
        whatsapp_templates_synced_at=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


# --------------------------------------------------------------------------- #
# Token
# --------------------------------------------------------------------------- #

def fake_inspect(info):
    async def _inspect(token):
        if isinstance(info, Exception):
            raise info
        return info
    return _inspect


@pytest.mark.asyncio
async def test_token_far_from_expiry_is_left_alone(monkeypatch):
    expires = real_now() + timedelta(days=50)
    monkeypatch.setattr(tl, "inspect_token", fake_inspect(tl.TokenInfo(True, expires)))

    async def no_refresh(token):
        raise AssertionError("must not refresh")

    monkeypatch.setattr(tl, "refresh_token", no_refresh)
    office = make_office(whatsapp_token_error="stale error")

    assert await tl.maintain_office_token(office, FakeDB()) == "ok"
    assert office.whatsapp_token_expires_at == expires
    assert office.whatsapp_token_checked_at is not None
    assert office.whatsapp_token_error is None


@pytest.mark.asyncio
async def test_token_inside_window_is_refreshed_and_stored(monkeypatch):
    monkeypatch.setattr(
        tl, "inspect_token", fake_inspect(tl.TokenInfo(True, real_now() + timedelta(days=20)))
    )
    new_expiry = real_now() + timedelta(days=60)

    async def refresh(token):
        assert token == "old-token"
        return "new-token", new_expiry

    monkeypatch.setattr(tl, "refresh_token", refresh)
    office = make_office()

    assert await tl.maintain_office_token(office, FakeDB()) == "refreshed"
    assert office.whatsapp_token == "new-token"
    assert office.whatsapp_token_expires_at == new_expiry


@pytest.mark.asyncio
async def test_failed_refresh_keeps_the_old_token_and_records_why(monkeypatch):
    monkeypatch.setattr(
        tl, "inspect_token", fake_inspect(tl.TokenInfo(True, real_now() + timedelta(days=5)))
    )

    async def refresh(token):
        raise WhatsAppError("boom")

    monkeypatch.setattr(tl, "refresh_token", refresh)
    office = make_office()

    assert await tl.maintain_office_token(office, FakeDB()) == "refresh_failed"
    assert office.whatsapp_token == "old-token"
    assert "Refresh failed" in office.whatsapp_token_error


@pytest.mark.asyncio
async def test_revoked_token_is_flagged(monkeypatch):
    monkeypatch.setattr(
        tl, "inspect_token", fake_inspect(tl.TokenInfo(False, None, "Session has been invalidated"))
    )
    office = make_office()

    assert await tl.maintain_office_token(office, FakeDB()) == "invalid"
    assert office.whatsapp_token_error == "Session has been invalidated"


@pytest.mark.asyncio
async def test_meta_outage_changes_nothing(monkeypatch):
    monkeypatch.setattr(tl, "inspect_token", fake_inspect(WhatsAppError("down")))
    office = make_office(whatsapp_token_error=None)
    db = FakeDB()

    assert await tl.maintain_office_token(office, db) == "check_failed"
    assert office.whatsapp_token_error is None and office.whatsapp_token_checked_at is None
    assert db.commits == 0


@pytest.mark.asyncio
async def test_non_expiring_token_is_never_refreshed(monkeypatch):
    monkeypatch.setattr(tl, "inspect_token", fake_inspect(tl.TokenInfo(True, None)))
    office = make_office()
    assert await tl.maintain_office_token(office, FakeDB()) == "ok"
    assert office.whatsapp_token_expires_at is None


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_sync_creates_only_missing_templates(monkeypatch):
    first, second, *rest = TEMPLATE_SPECS

    async def list_templates(waba_id, token):
        return {first.name: "APPROVED", second.name: "REJECTED", "someone_elses": "APPROVED"}

    created = []

    async def create_template(waba_id, token, spec):
        if spec.name == rest[0].name:
            raise WhatsAppError("refused")
        created.append(spec.name)
        return "PENDING"

    monkeypatch.setattr(tp, "list_templates", list_templates)
    monkeypatch.setattr(tp, "create_template", create_template)
    office = make_office()

    result = await tp.sync_office_templates(office, FakeDB())

    assert created == [s.name for s in rest[1:]]
    assert set(office.whatsapp_templates) == {s.name for s in TEMPLATE_SPECS}
    assert office.whatsapp_templates[first.name] == "APPROVED"
    assert office.whatsapp_templates[second.name] == "REJECTED"  # reported, not recreated
    assert office.whatsapp_templates[rest[0].name] == tp.MISSING
    assert result.pending and office.whatsapp_templates_synced_at is not None

    health = tp.template_health(office)
    assert health["approved"] == 1 and health["total"] == len(TEMPLATE_SPECS)
    assert health["problems"] == {second.name: "REJECTED", rest[0].name: tp.MISSING}


@pytest.mark.asyncio
async def test_sync_requires_a_connected_waba():
    with pytest.raises(WhatsAppError):
        await tp.sync_office_templates(make_office(whatsapp_waba_id=None), FakeDB())


# --------------------------------------------------------------------------- #
# Graph API parsing (httpx mocked at the transport)
# --------------------------------------------------------------------------- #

import httpx  # noqa: E402

REAL_ASYNC_CLIENT = httpx.AsyncClient


def mock_httpx(monkeypatch, module, handler):
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_inspect_token_reads_validity_and_expiry(monkeypatch):
    def handler(request):
        assert request.url.path.endswith("/debug_token")
        return httpx.Response(200, json={"data": {"is_valid": True, "expires_at": 1893456000}})

    mock_httpx(monkeypatch, tl, handler)
    info = await tl.inspect_token("t")
    assert info.valid and info.expires_at.year == 2030

    mock_httpx(monkeypatch, tl, lambda r: httpx.Response(200, json={"data": {"is_valid": True, "expires_at": 0}}))
    assert (await tl.inspect_token("t")).expires_at is None

    mock_httpx(
        monkeypatch, tl,
        lambda r: httpx.Response(200, json={"data": {"is_valid": False, "error": {"message": "expired"}}}),
    )
    assert await tl.inspect_token("t") == tl.TokenInfo(False, None, "expired")


@pytest.mark.asyncio
async def test_refresh_token_asks_for_a_60_day_system_user_token(monkeypatch):
    def handler(request):
        q = request.url.params
        assert q["grant_type"] == "fb_exchange_token"
        assert q["set_token_expires_in_60_days"] == "true"
        assert q["fb_exchange_token"] == "old"
        return httpx.Response(200, json={"access_token": "new", "expires_in": 5183944})

    mock_httpx(monkeypatch, tl, handler)
    token, expires_at = await tl.refresh_token("old")
    assert token == "new"
    assert timedelta(days=59) < expires_at - real_now() < timedelta(days=61)

    mock_httpx(monkeypatch, tl, lambda r: httpx.Response(400, json={"error": {"code": 190}}))
    with pytest.raises(WhatsAppError):
        await tl.refresh_token("old")


@pytest.mark.asyncio
async def test_list_templates_follows_paging_and_keeps_our_language(monkeypatch):
    def handler(request):
        if "after" not in str(request.url):
            return httpx.Response(200, json={
                "data": [
                    {"name": "a", "status": "APPROVED", "language": "es_MX"},
                    {"name": "b", "status": "APPROVED", "language": "en_US"},
                ],
                "paging": {"next": "https://graph.facebook.com/v21.0/waba/message_templates?after=X"},
            })
        return httpx.Response(200, json={"data": [{"name": "c", "status": "PENDING", "language": "es_MX"}]})

    mock_httpx(monkeypatch, tp, handler)
    assert await tp.list_templates("waba", "t") == {"a": "APPROVED", "c": "PENDING"}
