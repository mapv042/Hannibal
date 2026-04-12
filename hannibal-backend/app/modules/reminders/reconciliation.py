"""Reconciliation task — now lives in tasks.py as a shared_task.

This module is kept for backwards compatibility with any imports.
"""

from __future__ import annotations

from app.modules.reminders.tasks import reconcile_reminders  # noqa: F401
