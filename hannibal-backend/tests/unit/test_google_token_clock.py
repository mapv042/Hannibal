"""Google token expiry runs on real time, not the simulator's clock."""

from datetime import timedelta
from types import SimpleNamespace

from app.modules.google_calendar import auth
from app.utils.dates import real_now


def office_with(expires_at):
    return SimpleNamespace(google_calendar_token={
        "access_token": "old", "refresh_token": "r", "expires_at": expires_at.isoformat(),
    })


class DB:
    def __init__(self, office):
        self.office = office

    async def get(self, model, id_):
        return self.office


async def run(monkeypatch, expires_at, **kw):
    refreshed = []

    async def refresh(office_id, db):
        refreshed.append(1)
        return {"access_token": "new"}

    monkeypatch.setattr(auth, "refresh_google_token", refresh)
    token = await auth.get_valid_google_token("o", DB(office_with(expires_at)), **kw)
    return token, bool(refreshed)


async def test_valid_token_is_reused(monkeypatch):
    assert await run(monkeypatch, real_now() + timedelta(minutes=40)) == ("old", False)


async def test_expired_token_is_refreshed(monkeypatch):
    assert await run(monkeypatch, real_now() - timedelta(minutes=1)) == ("new", True)


async def test_expiry_written_under_a_moved_clock_is_refreshed(monkeypatch):
    # Stored while the simulator stood days ahead: impossible for a 1h token.
    assert await run(monkeypatch, real_now() + timedelta(days=4)) == ("new", True)


async def test_simulated_clock_offset_does_not_matter(monkeypatch):
    import app.core.clock as clock
    monkeypatch.setattr(clock, "clock_offset", lambda: timedelta(days=5))
    assert await run(monkeypatch, real_now() + timedelta(minutes=40)) == ("old", False)


async def test_force_refresh(monkeypatch):
    assert await run(monkeypatch, real_now() + timedelta(minutes=40), force_refresh=True) == ("new", True)
