"""Celery application configuration for Hannibal backend."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.utils.logger import configure_logging

# Structured JSON logs (same format as the API) for workers and beat
configure_logging("INFO")

# Create Celery app
celery_app = Celery(
    "hannibal",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Redis re-delivers any message a worker holds without acking for longer than
# `visibility_timeout` (default 1h). Reminders are `eta` tasks that sit in the
# worker until the appointment, so with the default every reminder scheduled
# more than an hour ahead was re-delivered hourly and ran once per copy (the
# duplicated post-appointment follow-ups). It must exceed the longest eta we
# enqueue, i.e. the booking horizon. The trade-off is that a hard-killed worker
# (SIGKILL; a clean shutdown restores its unacked messages) leaves its tasks
# invisible for this long — `reconcile_reminders` is the safety net that
# re-schedules unsent reminders for the next two days.
BROKER_VISIBILITY_TIMEOUT_SECONDS = 60 * 60 * 24 * 60  # 60 days

# Configure Celery
celery_app.conf.update(
    broker_transport_options={"visibility_timeout": BROKER_VISIBILITY_TIMEOUT_SECONDS},
    result_backend_transport_options={
        "visibility_timeout": BROKER_VISIBILITY_TIMEOUT_SECONDS
    },
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
    # Result backend configuration
    result_expires=3600,  # Results expire after 1 hour
    # Beat schedule for periodic tasks
    beat_schedule={
        "renew-google-watches": {
            "task": "app.modules.google_calendar.tasks.renew_google_watches",
            "schedule": crontab(minute=0, hour=0),  # Daily at midnight
            "options": {"queue": "celery"},
        },
        "reconcile-reminders": {
            "task": "app.modules.reminders.tasks.reconcile_reminders",
            "schedule": crontab(minute=0, hour=7),  # Daily at 7:00 AM (before 8 AM morning reminders)
            "options": {"queue": "celery"},
        },
        "send-confirmation-requests": {
            "task": "app.modules.reminders.tasks.send_confirmation_requests",
            "schedule": crontab(minute=settings.confirmation_request_minute, hour=settings.confirmation_request_hour),
            "options": {"queue": "celery"},
        },
        "send-unconfirmed-summaries": {
            "task": "app.modules.notifications.tasks.send_unconfirmed_summaries",
            "schedule": crontab(minute="*/15"),  # checks each office; fires 1h before its first block
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
])

# Ensure task modules are imported so Celery registers them
import app.modules.reminders.tasks  # noqa: F401
import app.modules.urgencies.tasks  # noqa: F401
import app.modules.scheduling.tasks  # noqa: F401
import app.modules.notifications.tasks  # noqa: F401
import app.modules.google_calendar.tasks  # noqa: F401
import app.modules.audit.tasks  # noqa: F401
