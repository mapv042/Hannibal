"""The offset that lets the simulator move time without lying to the code.

Everything that asks "what time is it?" goes through `app.utils.dates.now_mx`,
which adds the offset kept here. In normal operation the offset is zero and
`now_mx()` is a plain `datetime.now(MX_TIMEZONE)`; under the conversation
simulator it is however far ahead the operator has pushed the clock, so a
reminder due in three days can be made due now.

Why a ContextVar and not a module global: the offset is read on nearly every
request and task, and it lives in Redis so the API and the Celery worker agree
on it. Reading Redis per `now_mx()` call would be a round trip per timestamp, so
the offset is loaded **once per request** (API middleware) and **once per task**
(Celery `task_prerun`) and stashed here for the rest of that unit of work. A
ContextVar is what keeps two concurrent requests from seeing each other's value.

Safety: the offset is ignored outright when `ENVIRONMENT=production`, so a stray
`SIMULATION_MODE` in a production environment cannot move time. `simulation_enabled()`
is the single place that decides, and everything else asks it.

The clock only ever moves **forward**. Google Calendar does not travel in time,
so rewinding would have us asking it about dates that no longer line up with the
appointments we wrote. Resetting a scenario means destroying and reseeding, not
rewinding.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import timedelta

# Seconds added to real time. Zero everywhere except inside a simulator run.
_offset_seconds: ContextVar[int] = ContextVar("sim_clock_offset_seconds", default=0)


def simulation_enabled() -> bool:
    """Whether the virtual clock may be moved at all.

    False in production no matter how the environment is configured: the flag is
    a development affordance, and a production deployment that somehow carried it
    must behave as if it were absent.
    """
    from app.config import settings

    return settings.simulation_mode and not settings.is_production


def clock_offset() -> timedelta:
    """How far ahead of real time the virtual clock currently is."""
    if not simulation_enabled():
        return timedelta(0)

    return timedelta(seconds=_offset_seconds.get())


def set_clock_offset(seconds: int) -> None:
    """Set the offset for the current request or task.

    Args:
        seconds: Seconds ahead of real time. Never negative — the clock only
            moves forward (see the module docstring).

    Raises:
        ValueError: If `seconds` is negative.
    """
    if seconds < 0:
        raise ValueError("the simulated clock only moves forward")

    _offset_seconds.set(seconds)
