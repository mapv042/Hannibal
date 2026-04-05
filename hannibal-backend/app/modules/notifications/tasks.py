"""Celery tasks for notification handling."""

from __future__ import annotations

from uuid import UUID
from typing import Dict, Any
import asyncio

from app.modules.notifications.service import notify_doctor
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CeleryTaskStub:
    """Stub for Celery task decorator during development."""

    def __call__(self, func):
        func.apply_async = self._apply_async
        return func

    @staticmethod
    def _apply_async(*args, **kwargs):
        """Stub for apply_async."""
        pass


def celery_task(*args, **kwargs):
    """Stub Celery task decorator."""
    return CeleryTaskStub()


@celery_task(bind=True)
def send_doctor_notification(
    self,
    office_id: str,
    notification_type: str,
    data: Dict[str, Any],
):
    """
    Celery task to send notification to medical professional.

    Args:
        office_id: Office ID (string)
        notification_type: Notification type
        data: Notification data
    """
    asyncio.run(
        notify_doctor(
            office_id=UUID(office_id),
            notification_type=notification_type,
            data=data,
        )
    )
