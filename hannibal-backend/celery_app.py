"""Celery application configuration for Hannibal backend."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings

# Create Celery app
celery_app = Celery(
    "hannibal",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Configure Celery
celery_app.conf.update(
    # Timezone
    timezone="America/Mexico_City",
    enable_utc=True,
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
            "schedule": crontab(minute=0, hour="*/24"),  # Every 24 hours
            "options": {"queue": "celery"},
        },
        "reconcile-reminders": {
            "task": "app.modules.reminders.tasks.reconcile_reminders",
            "schedule": crontab(minute=0, hour=1),  # Daily at 1:00 AM
            "options": {"queue": "celery"},
        },
        "send-confirmation-requests": {
            "task": "app.modules.reminders.tasks.send_confirmation_requests",
            "schedule": crontab(minute=settings.confirmation_request_minute, hour=settings.confirmation_request_hour),
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
])

# Explicitly import tasks to ensure they are registered
import sys
try:
    import app.modules.reminders.tasks  # noqa: F401
    print("[CELERY_APP] reminders.tasks imported OK", file=sys.stderr, flush=True)
    print(f"[CELERY_APP] registered tasks: {list(celery_app.tasks.keys())}", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[CELERY_APP] FAILED to import reminders.tasks: {e}", file=sys.stderr, flush=True)
    import traceback
    traceback.print_exc(file=sys.stderr)
