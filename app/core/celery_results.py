"""Read Celery outcomes without blocking status requests."""

import asyncio
import logging
from uuid import UUID

logger = logging.getLogger(__name__)


def _failed_task_message(task_id: UUID) -> str | None:
    from workers.celery_app import celery_app

    result = celery_app.backend.get_task_meta(str(task_id))
    if result["status"] != "FAILURE":
        return None
    return str(result.get("result") or "Celery reported a task failure")


async def failed_task_message(task_id: UUID) -> str | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_failed_task_message, task_id), timeout=2
        )
    except Exception:
        logger.warning(
            "Could not read Celery outcome for task %s", task_id, exc_info=True
        )
        return None
