"""Safe dispatch of Celery tasks from request and tool code.

A queued side effect must never turn a successful write into a user-visible
failure. Before this existed, `apply_async` was called bare from the tool
handlers: a broker hiccup raised straight into the handler, the executor caught
it and returned "ocurrió un error" — while the appointment it had just written
stayed in the transaction and was committed at the end of the turn. The patient
was told the booking failed for a booking that exists.

Every enqueue helper goes through `dispatch`, which logs the failure and returns
False instead of raising. A late notification is recoverable; a lie about what
happened is not.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from app.utils.logger import get_logger

logger = get_logger(__name__)


def dispatch(
    task: Any,
    args: Sequence[Any],
    *,
    event: str,
    countdown: Optional[int] = None,
    eta: Optional[datetime] = None,
    **log_fields: Any,
) -> bool:
    """Queue a Celery task, never raising into the caller.

    Args:
        task: The Celery task object.
        args: Positional arguments for the task.
        event: structlog event name, used for both the success and failure log.
        countdown: Seconds to wait before the task becomes eligible.
        eta: Absolute time the task becomes eligible (mutually exclusive with
            `countdown`).
        **log_fields: Extra context attached to both log lines.

    Returns:
        True if the broker accepted the message, False if it was dropped.
    """
    try:
        task.apply_async(args=list(args), countdown=countdown, eta=eta)
    except Exception as e:
        logger.error(f"{event}_enqueue_failed", error=str(e), exc_info=True, **log_fields)
        return False

    logger.info(event, **log_fields)
    return True
