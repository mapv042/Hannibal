"""Celery application configuration for Hannibal backend."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.utils.logger import configure_logging, get_logger

# Structured JSON logs (same format as the API) for workers and beat
configure_logging("INFO")

# Create Celery app.
#
# The result backend is optional and off by default. Nothing in this codebase
# ever reads a task result — every enqueue goes through app.core.celery_dispatch,
# which ignores the AsyncResult on purpose — so storing results buys nothing and
# costs a second Redis connection per publish. It also turned out to be a real
# failure mode: under a burst of publishes the API process logged "Retry limit
# exceeded while trying to reconnect to the Celery result store backend" and
# apply_async started failing, so the reminder sweep reported zero dispatched
# while reminders were genuinely due. Set CELERY_RESULT_BACKEND to turn it back
# on if a task ever needs to return something.
celery_app = Celery(
    "hannibal",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend or None,
)

# Reminders are no longer far-future `eta` tasks held in a worker's memory (see
# app.modules.reminders.tasks), so Redis' default visibility timeout is fine
# again: every task this app queues is meant to run within minutes.

# Configure Celery
celery_app.conf.update(
    # Timezone. enable_utc must stay False: with it enabled, beat interprets
    # crontab hours in UTC and the daily tasks fire 6h early (madrugada MX).
    timezone="America/Mexico_City",
    enable_utc=False,
    # Task configuration
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes hard limit
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit
    # Results are not stored unless a backend is configured (see above).
    task_ignore_result=not settings.celery_result_backend,
    result_expires=3600,  # Results expire after 1 hour, when stored at all
    # Beat schedule for periodic tasks
    beat_schedule={
        "renew-google-watches": {
            "task": "app.modules.google_calendar.tasks.renew_google_watches",
            "schedule": crontab(minute=0, hour=0),  # Daily at midnight
            "options": {"queue": "celery"},
        },
        "dispatch-due-reminders": {
            "task": "app.modules.reminders.tasks.dispatch_due_reminders",
            "schedule": crontab(minute="*/5"),  # the single reminder clock
            "options": {"queue": "celery"},
        },
        "send-unconfirmed-summaries": {
            "task": "app.modules.notifications.tasks.send_unconfirmed_summaries",
            "schedule": crontab(minute="*/15"),  # checks each office; fires 1h before its first block
            "options": {"queue": "celery"},
        },
        "prune-turn-traces": {
            "task": "app.modules.conversation.tasks.prune_turn_traces",
            "schedule": crontab(minute=30, hour=3),  # daily, off-hours
            "options": {"queue": "celery"},
        },
    },
)

# Auto-discover tasks from app.modules
celery_app.autodiscover_tasks([
    "app.modules.whatsapp",
    "app.modules.scheduling",
    "app.modules.reminders",
    "app.modules.notifications",
    "app.modules.google_calendar",
    "app.modules.urgencies",
    "app.modules.audit",
    "app.modules.conversation",
])

# Ensure task modules are imported so Celery registers them
import app.modules.reminders.tasks  # noqa: F401
import app.modules.urgencies.tasks  # noqa: F401
import app.modules.scheduling.tasks  # noqa: F401
import app.modules.notifications.tasks  # noqa: F401
import app.modules.google_calendar.tasks  # noqa: F401
import app.modules.audit.tasks  # noqa: F401
import app.modules.conversation.tasks  # noqa: F401

# --------------------------------------------------------------------------- #
# Simulated clock
# --------------------------------------------------------------------------- #
# Tasks have to see the same "now" the API does. Without this the worker runs on
# real time while the simulator has moved days ahead, and every reminder it
# writes gets the wrong date — a message saying "mañana" about an appointment
# three days out. The offset is read once per task rather than per timestamp.
#
# The import is inside the guard on purpose: app.modules.sim refuses to import in
# production, and celery_app is imported there.
if settings.simulation_mode and not settings.is_production:
    from celery.signals import task_prerun

    @task_prerun.connect
    def _load_simulated_clock(**_kwargs):  # pragma: no cover - worker-side hook
        import redis

        from app.core.clock import set_clock_offset
        from app.modules.sim.runner import CLOCK_KEY

        client = redis.from_url(settings.redis_url, decode_responses=True)
        try:
            raw = client.get(CLOCK_KEY)
            set_clock_offset(int(raw) if raw else 0)
        except Exception as e:  # a missing offset must not kill the task
            logger = get_logger(__name__)
            logger.warning("sim_clock_load_failed", error=str(e))
        finally:
            client.close()

