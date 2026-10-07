"""Celery tasks for the conversation module."""

from __future__ import annotations

from celery import shared_task

from app.core.task_runner import run_task
from app.db.base import get_async_session_maker
from app.modules.conversation.tracing import TRACE_RETENTION_DAYS, prune_old_traces
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _prune_turn_traces_async() -> int:
    async with get_async_session_maker()() as db:
        return await prune_old_traces(db)


async def _prune_old_messages_async() -> int:
    from app.modules.privacy.retention import prune_old_messages

    async with get_async_session_maker()() as db:
        return await prune_old_messages(db)


@shared_task(name="app.modules.conversation.tasks.prune_old_messages")
def prune_old_messages() -> None:
    """Drop WhatsApp messages past the retention window the privacy notice promises."""
    deleted = run_task(_prune_old_messages_async())
    logger.info("messages_pruned", deleted=deleted)


@shared_task(name="app.modules.conversation.tasks.prune_turn_traces")
def prune_turn_traces() -> None:
    """Drop ai_turn_traces older than the retention window (patient data)."""
    deleted = run_task(_prune_turn_traces_async())
    logger.info(
        "turn_traces_pruned", deleted=deleted, retention_days=TRACE_RETENTION_DAYS
    )
