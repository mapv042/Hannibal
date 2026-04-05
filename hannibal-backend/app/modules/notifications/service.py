"""Service layer for notifications (sending alerts to medical professional)."""

from __future__ import annotations

from uuid import UUID
from typing import Optional, Dict, Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


async def notify_doctor(
    office_id: UUID,
    notification_type: str,
    data: Dict[str, Any],
) -> None:
    """
    Send notification to medical professional.

    Types:
        new_appointment: New appointment created
        appointment_cancelled: Appointment cancelled
        patient_not_confirmed: Patient hasn't confirmed appointment
        new_patient: New patient registered
        urgent_message: Urgent message from patient

    Args:
        office_id: Office ID
        notification_type: Notification type
        data: Notification data (varies by type)

    Example data structures:
        new_appointment: {appointment_id, patient_name, date_time, reason}
        appointment_cancelled: {appointment_id, patient_name, reason}
        patient_not_confirmed: {appointment_id, patient_name, hours_until_appointment}
        new_patient: {patient_name, phone, main_reason}
        urgent_message: {patient_name, message}
    """
    try:
        logger.info(
            "notify_doctor",
            office_id=str(office_id),
            notification_type=notification_type,
            data=data,
        )

        # TODO: Implement actual notification sending:
        # - Push notification via Firebase Cloud Messaging
        # - WhatsApp direct message to doctor
        # - Email to doctor
        # - In-app notification dashboard

        match notification_type:
            case "new_appointment":
                await _notify_new_appointment(office_id, data)
            case "appointment_cancelled":
                await _notify_appointment_cancelled(office_id, data)
            case "patient_not_confirmed":
                await _notify_patient_not_confirmed(office_id, data)
            case "new_patient":
                await _notify_new_patient(office_id, data)
            case "urgent_message":
                await _notify_urgent_message(office_id, data)
            case _:
                logger.warning(
                    "unknown_notification_type",
                    notification_type=notification_type,
                    office_id=str(office_id),
                )

    except Exception as e:
        logger.error(
            "error_notify_doctor",
            office_id=str(office_id),
            notification_type=notification_type,
            error=str(e),
        )


async def _notify_new_appointment(
    office_id: UUID,
    data: Dict[str, Any],
) -> None:
    """Send notification for new appointment."""
    message = (
        f"New appointment scheduled\n"
        f"Patient: {data.get('patient_name', 'N/A')}\n"
        f"Date/Time: {data.get('date_time', 'N/A')}\n"
        f"Reason: {data.get('reason', 'N/A')}"
    )

    logger.info(
        "notify_new_appointment",
        office_id=str(office_id),
        message=message,
    )

    # TODO: Send to doctor via FCM, WhatsApp, email


async def _notify_appointment_cancelled(
    office_id: UUID,
    data: Dict[str, Any],
) -> None:
    """Send notification for cancelled appointment."""
    message = (
        f"Appointment cancelled\n"
        f"Patient: {data.get('patient_name', 'N/A')}\n"
        f"Reason: {data.get('reason', 'N/A')}"
    )

    logger.info(
        "notify_appointment_cancelled",
        office_id=str(office_id),
        message=message,
    )

    # TODO: Send to doctor


async def _notify_patient_not_confirmed(
    office_id: UUID,
    data: Dict[str, Any],
) -> None:
    """Send notification if patient hasn't confirmed appointment."""
    hours = data.get("hours_until_appointment", "N/A")
    message = (
        f"⚠️ Appointment not confirmed\n"
        f"Patient: {data.get('patient_name', 'N/A')}\n"
        f"Time until appointment: {hours} hours"
    )

    logger.info(
        "notify_patient_not_confirmed",
        office_id=str(office_id),
        message=message,
    )

    # TODO: Send to doctor


async def _notify_new_patient(
    office_id: UUID,
    data: Dict[str, Any],
) -> None:
    """Send notification for new patient registration."""
    message = (
        f"New patient registered\n"
        f"Name: {data.get('patient_name', 'N/A')}\n"
        f"Phone: {data.get('phone', 'N/A')}\n"
        f"Reason: {data.get('main_reason', 'N/A')}"
    )

    logger.info(
        "notify_new_patient",
        office_id=str(office_id),
        message=message,
    )

    # TODO: Send to doctor


async def _notify_urgent_message(
    office_id: UUID,
    data: Dict[str, Any],
) -> None:
    """Send notification for urgent message from patient."""
    message = (
        f"🚨 Urgent message\n"
        f"Patient: {data.get('patient_name', 'N/A')}\n"
        f"Message: {data.get('message', 'N/A')}"
    )

    logger.info(
        "notify_urgent_message",
        office_id=str(office_id),
        message=message,
    )

    # TODO: Send to doctor immediately via all channels
