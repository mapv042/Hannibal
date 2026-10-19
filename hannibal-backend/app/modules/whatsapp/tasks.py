"""Celery tasks that keep each office's WhatsApp connection usable.

- `maintain_whatsapp_accounts` (beat, daily): for every connected office, check
  and refresh its 60-day token (token_lifecycle.py), then sync its templates
  (template_provisioning.py) — creating any added to the catalogue since.
- `provision_office_templates` (on demand, right after Embedded Signup): create
  the templates on the new WABA, then re-check every few minutes while Meta is
  still reviewing them, so the dashboard shows "approved" the same hour.
"""

from __future__ import annotations

from uuid import UUID

from celery import shared_task
from sqlalchemy import select

from app.core.celery_dispatch import dispatch
from app.core.exceptions import WhatsAppError
from app.core.task_runner import run_task
from app.db.base import get_async_session_maker
from app.db.models import Office
from app.modules.whatsapp.template_provisioning import sync_office_templates
from app.modules.whatsapp.token_lifecycle import maintain_office_token
from app.modules.whatsapp.transport import use_fake_transport
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Utility templates are usually reviewed within minutes; re-check for ~1h.
TEMPLATE_RECHECK_SECONDS = 600
TEMPLATE_RECHECK_ATTEMPTS = 6
# Give the signup request time to commit before the first sync reads the office.
PROVISION_COUNTDOWN_SECONDS = 5


def _log(msg: str) -> None:
    logger.info("celery_task", detail=msg)


def _log_exception(task_name: str, e: Exception) -> None:
    logger.error("celery_task_failed", task=task_name, error=str(e), exc_info=True)


def enqueue_template_provisioning(office_id: str, attempt: int = 1) -> bool:
    """Queue template provisioning for an office (never raises)."""
    return dispatch(
        provision_office_templates,
        [office_id, attempt],
        event="wa_templates_provision_enqueued",
        countdown=PROVISION_COUNTDOWN_SECONDS if attempt == 1 else TEMPLATE_RECHECK_SECONDS,
        office_id=office_id,
        attempt=attempt,
    )


async def _maintain_whatsapp_accounts_async() -> dict:
    counts: dict = {}
    if use_fake_transport():
        # The simulator's office carries junk credentials on purpose.
        _log("maintain_whatsapp_accounts: skipped (fake transport)")
        return counts

    session_maker = get_async_session_maker()
    async with session_maker() as db:
        office_ids = (
            await db.execute(select(Office.id).where(Office.whatsapp_token.isnot(None)))
        ).scalars().all()

    # A session per office: one office failing (and rolling back) must neither
    # block the rest nor expire their loaded rows.
    for office_id in office_ids:
        async with session_maker() as db:
            office = await db.get(Office, office_id)
            if office is None:
                continue
            has_waba = bool(office.whatsapp_waba_id)
            try:
                outcome = await maintain_office_token(office, db)
            except Exception as e:
                logger.error("wa_token_maintenance_error", office_id=str(office_id), error=str(e))
                outcome = "error"
            counts[outcome] = counts.get(outcome, 0) + 1

            if outcome in ("invalid", "error") or not has_waba:
                continue
            try:
                await sync_office_templates(office, db)
            except Exception as e:
                logger.error("wa_templates_sync_error", office_id=str(office_id), error=str(e))

    _log(f"maintain_whatsapp_accounts: DONE {counts}")
    return counts


@shared_task(bind=True)
def maintain_whatsapp_accounts(self):
    """Beat task: refresh expiring WhatsApp tokens and sync templates."""
    _log("maintain_whatsapp_accounts: START")
    try:
        run_task(_maintain_whatsapp_accounts_async())
    except Exception as e:
        _log_exception("maintain_whatsapp_accounts", e)
        raise


async def _provision_office_templates_async(office_id: str) -> bool:
    """Sync the office's templates; True while some are still under review."""
    async with get_async_session_maker()() as db:
        office = await db.get(Office, UUID(office_id))
        if office is None or not office.whatsapp_waba_id or not office.whatsapp_token:
            _log(f"provision_office_templates: office={office_id} not connected, skipped")
            return False
        try:
            result = await sync_office_templates(office, db)
        except WhatsAppError as e:
            logger.error("wa_templates_provision_failed", office_id=office_id, error=str(e))
            return True  # couldn't even list; worth another try
        return result.pending


@shared_task(bind=True)
def provision_office_templates(self, office_id: str, attempt: int = 1):
    """Create the office's templates and follow them until Meta decides."""
    if use_fake_transport():
        return
    try:
        still_pending = run_task(_provision_office_templates_async(office_id))
    except Exception as e:
        _log_exception("provision_office_templates", e)
        raise
    if still_pending and attempt < TEMPLATE_RECHECK_ATTEMPTS:
        enqueue_template_provisioning(office_id, attempt + 1)
