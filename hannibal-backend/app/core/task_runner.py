"""The single entry point Celery tasks use to run their async body.

Every task in `app/modules/*/tasks.py` is a sync Celery function wrapping an
async one. Calling `asyncio.run()` directly is what broke them: it opens a fresh
event loop per task and closes it on exit, while the SQLAlchemy engine is a
process-level global whose asyncpg connections stay bound to the loop that
opened them. The first task after a worker boots worked; every later one in that
process failed on a dead connection.

`run_task` keeps the fresh-loop-per-task model — it is what makes tasks
independent — and just closes the engine before the loop goes away, so no
connection ever outlives its loop. Redis clients need no such care: the task
bodies build them inside the coroutine, so they belong to the running loop
already.

Use this for every Celery task body. Do not use it in the API process, where one
long-lived pool across requests is the right thing.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

from app.db.base import dispose_engine

T = TypeVar("T")


def run_task(coro: Coroutine[Any, Any, T]) -> T:
    """Run a task's coroutine in its own loop, disposing the DB engine after.

    Args:
        coro: The already-created coroutine holding the task body.

    Returns:
        Whatever the coroutine returns.

    Raises:
        Whatever the coroutine raises — the dispose runs either way, so a failing
        task still leaves a clean engine behind for the next one.
    """

    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())
