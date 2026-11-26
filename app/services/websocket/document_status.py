"""WebSocket streaming for document processing status.

Subscribes to Redis pub/sub channel `document_updates:{document_id}`
and relays messages to the WebSocket client until the task completes
or fails.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from app.core.constant import FileStatus, PIPELINE_STEP_TOTAL
from app.core.database import async_session
from app.core.redis_client import get_async_redis_client
from app.services.document_status import (
    document_failure_message,
    reconcile_replacement_start_failure,
    resolve_document_status,
)

logger = logging.getLogger("memory_rag.ws.document_status")
TERMINAL_STATUSES = {
    FileStatus.COMPLETED.value,
    FileStatus.FAILED.value,
    FileStatus.CANCELLED.value,
}


def _parse_step_number(step: str | int | None) -> int | None:
    """Convert current and legacy persisted step values to a number."""
    if step is None:
        return None

    try:
        return int(str(step).split("/", 1)[0])
    except (TypeError, ValueError):
        logger.warning("Invalid persisted pipeline step: %r", step)
        return None


async def _get_current_state(document_id: str) -> dict | None:
    """Read the document's latest state from the DB (async).

    Returns the most recent ``document_events`` row ordered by
    ``created_at DESC``, or a fallback dict built from the ``documents``
    table if no history exists yet, or ``None`` if the document itself
    is not found.
    """
    from sqlalchemy import select

    from app.models.document import Document
    from app.models.document_event import DocumentEventModel
    from app.models.workspace import WorkspaceModel

    doc_uuid = UUID(document_id)
    async with async_session() as db:
        document_result = await db.execute(
            select(Document, WorkspaceModel.name)
            .join(WorkspaceModel, WorkspaceModel.id == Document.workspace_id)
            .where(Document.id == doc_uuid)
        )
        document_row = document_result.one_or_none()
        if document_row is None:
            return None
        document, workspace_name = document_row

        history_result = await db.execute(
            select(DocumentEventModel)
            .where(DocumentEventModel.document_id == doc_uuid)
            .order_by(
                DocumentEventModel.created_at.desc(), DocumentEventModel.id.desc()
            )
            .limit(1)
        )
        history = history_result.scalar_one_or_none()
        failure = await reconcile_replacement_start_failure(db, document, history)
        if failure is not None:
            await db.commit()
            history = failure
        if document.status == FileStatus.CANCELLING.value:
            cancellation_result = await db.execute(
                select(DocumentEventModel)
                .where(
                    DocumentEventModel.document_id == doc_uuid,
                    DocumentEventModel.status == FileStatus.CANCELLING.value,
                )
                .order_by(
                    DocumentEventModel.created_at.desc(),
                    DocumentEventModel.id.desc(),
                )
                .limit(1)
            )
            history = cancellation_result.scalar_one_or_none() or history
        effective_status, worker_stopped = await resolve_document_status(
            db, document, history
        )
        message = (
            history.message
            if history and history.message
            else "Document is being processed"
        )
        if document.status == FileStatus.CANCELLING.value:
            message = document.last_error or "Cancellation cleanup is in progress"
        if effective_status == FileStatus.FAILED.value:
            message = document_failure_message(document, history, worker_stopped)

        if history is not None:
            return {
                "type": "current_state",
                "status": effective_status,
                "stage": history.stage,
                "step": _parse_step_number(history.step),
                "stepTotal": PIPELINE_STEP_TOTAL,
                "message": message,
                "document_id": document_id,
                "original_filename": document.original_filename,
                "workspace_name": workspace_name,
                "page_number": history.page_number,
                "total_pages": history.total_pages,
                "timestamp": (
                    history.created_at.isoformat() if history.created_at else None
                ),
            }

        # No history yet — fall back to document's current status
        return {
            "type": "current_state",
            "status": effective_status or "",
            "stage": None,
            "step": None,
            "stepTotal": PIPELINE_STEP_TOTAL,
            "message": message,
            "document_id": document_id,
            "original_filename": document.original_filename,
            "workspace_name": workspace_name,
            "page_number": None,
            "total_pages": document.page_count,
            "timestamp": (
                document.created_at.isoformat() if document.created_at else None
            ),
        }


async def stream_document_status(
    document_id: str, send: Callable[[dict], Awaitable[None]]
) -> None:
    redis_async = await get_async_redis_client()
    async with redis_async.pubsub() as pubsub:
        # Subscribe first so a fast retry cannot finish between the snapshot and subscription.
        await pubsub.subscribe(f"document_updates:{document_id}")
        current_state = await _get_current_state(document_id)
        if current_state is None:
            return
        await send(current_state)
        if current_state.get("status") in TERMINAL_STATUSES:
            return

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=30.0
            )
            if message is None:
                try:
                    current_state = await _get_current_state(document_id)
                    if current_state is None:
                        await send(
                            {
                                "type": "current_state",
                                "status": FileStatus.CANCELLED.value,
                                "document_id": document_id,
                                "message": "Document was removed.",
                            }
                        )
                        break
                    if (
                        current_state
                        and current_state.get("status") in TERMINAL_STATUSES
                    ):
                        await send(current_state)
                        break
                    await send({"type": "ping"})
                except Exception:
                    break
                continue
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            if data.get("status") == FileStatus.CANCELLED.value:
                await send(data)
                break
            if data.get("status") in TERMINAL_STATUSES:
                # A delayed terminal notification must not close a newer retry's stream.
                current_state = await _get_current_state(document_id)
                if current_state and current_state.get("status") in TERMINAL_STATUSES:
                    await send(current_state)
                    break
                continue
            await send(data)
