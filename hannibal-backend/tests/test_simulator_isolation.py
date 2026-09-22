"""The simulator must never be reachable in production.

These are guard tests, not behaviour tests: each one asserts a property that
someone could plausibly undo by accident in six months — a router mounted
unconditionally, a flag read from the wrong place, an import moved to the top of
a module. The cost of the regression is a production backend that can be told it
is next Thursday, so it is worth pinning down.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from app.config import settings


@pytest.fixture
def production_env(monkeypatch):
    """Configure settings as a production deployment, and reload nothing yet."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "simulation_mode", True)
    yield


def _reload_app():
    """Re-import app.main so router mounting re-runs under current settings."""
    for name in [m for m in sys.modules if m.startswith("app.main")]:
        del sys.modules[name]
    return importlib.import_module("app.main")


def test_sim_module_refuses_to_import_in_production(production_env):
    """The strongest guard: importing the package at all must fail."""
    for name in [m for m in list(sys.modules) if m.startswith("app.modules.sim")]:
        del sys.modules[name]

    with pytest.raises(RuntimeError, match="never be imported in production"):
        importlib.import_module("app.modules.sim")


def test_no_sim_routes_when_production(production_env):
    """Even with SIMULATION_MODE on, a production app exposes no /api/sim route."""
    for name in [m for m in list(sys.modules) if m.startswith("app.modules.sim")]:
        del sys.modules[name]

    main = _reload_app()
    sim_routes = [r.path for r in main.app.routes if r.path.startswith("/api/sim")]

    assert sim_routes == [], f"simulator reachable in production: {sim_routes}"


def test_no_sim_routes_when_flag_off(monkeypatch):
    """Outside production the flag still has to be on for the routes to exist."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "simulation_mode", False)

    main = _reload_app()
    sim_routes = [r.path for r in main.app.routes if r.path.startswith("/api/sim")]

    assert sim_routes == []


def test_sim_routes_exist_when_enabled(monkeypatch):
    """And they do appear when it is switched on, or the test above proves nothing."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "simulation_mode", True)

    main = _reload_app()
    sim_routes = [r.path for r in main.app.routes if r.path.startswith("/api/sim")]

    assert "/api/sim/clock" in sim_routes
    assert "/api/sim/inbound" in sim_routes


def test_fake_whatsapp_transport_refused_in_production(monkeypatch):
    """The transport seam has the same rule: no faking in production."""
    from app.modules.whatsapp.meta_client import MetaCloudClient
    from app.modules.whatsapp.transport import get_meta_client

    monkeypatch.setattr(settings, "whatsapp_transport", "fake")
    monkeypatch.setattr(settings, "environment", "production")

    assert isinstance(get_meta_client(), MetaCloudClient)


def test_clock_offset_ignored_in_production(monkeypatch):
    """A stray SIMULATION_MODE cannot move production's clock."""
    from datetime import timedelta

    from app.core.clock import clock_offset, set_clock_offset

    monkeypatch.setattr(settings, "simulation_mode", True)
    monkeypatch.setattr(settings, "environment", "production")
    set_clock_offset(3 * 24 * 3600)

    assert clock_offset() == timedelta(0)
