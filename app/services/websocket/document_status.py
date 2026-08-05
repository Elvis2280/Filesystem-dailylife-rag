"""WebSocket streaming for document processing status.

Subscribes to Redis pub/sub channel `document_updates:{document_id}`
and relays messages to the WebSocket client until the task completes
or fails.
"""

import json
import logging
from uuid import UUID

from app.core.constant import FileStatus
from app.core.database import async_session
from app.core.redis_client import get_async_redis_client
from app.core.websocket_manager import manager

logger = logging.getLogger("memory_rag.ws.document_status")


async def _get_current_state(document_id: str) -> dict | None:
    """Read the document's latest state from the DB (async).

    Returns the most recent ``document_history`` row ordered by
    ``created_at DESC``, or a fallback dict built from the ``documents``
    table if no history exists yet, or ``None`` if the document itself
    is not found.
    """
    from sqlalchemy import select

    from app.models.document import Document
    from app.models.document_history import DocumentHistoryModel

    doc_uuid = UUID(document_id)
    async with async_session() as db:
        history_result = await db.execute(
            select(DocumentHistoryModel)
            .where(DocumentHistoryModel.document_id == doc_uuid)
            .order_by(DocumentHistoryModel.created_at.desc())
            .limit(1)
        )
        history = history_result.scalar_one_or_none()

        if history is not None:
            return {
                "type": "current_state",
                "status": history.status,
                "stage": history.stage,
                "step": history.step,
                "message": history.message,
                "document_id": document_id,
                "page_number": history.page_number,
                "total_pages": history.total_pages,
                "timestamp": (
                    history.created_at.isoformat() if history.created_at else None
                ),
            }

        # No history yet — fall back to document's current status
        doc_result = await db.execute(select(Document).where(Document.id == doc_uuid))
        doc = doc_result.scalar_one_or_none()

        if doc is None:
            return None

        return {
            "type": "current_state",
            "status": doc.status or "",
            "stage": None,
            "step": None,
            "message": "Pending",
            "document_id": document_id,
            "page_number": None,
            "total_pages": doc.page_count,
            "timestamp": (doc.created_at.isoformat() if doc.created_at else None),
        }


async def _send_current_state(document_id: str) -> dict | None:
    """Fetch the latest state from the DB and send it to the WebSocket."""
    state = await _get_current_state(document_id)
    if state is not None:
        await manager.send_message(document_id, state)
    return state


async def stream_document_status(document_id: str) -> None:
    # Send current state first so the client immediately knows the document status
    current_state = None
    try:
        current_state = await _send_current_state(document_id)
    except Exception:
        logger.exception("Failed to send current state for %s", document_id)

    # If the document is already in a terminal state, close immediately
    if current_state is not None and current_state.get("status") in (
        FileStatus.COMPLETED.value,
        FileStatus.FAILED.value,
    ):
        return

    redis_async = await get_async_redis_client()
    pubsub = redis_async.pubsub()
    await pubsub.subscribe(f"document_updates:{document_id}")
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=30.0
            )
            if message is None:
                try:
                    await manager.send_message(document_id, {"type": "ping"})
                except Exception:
                    break
                continue
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            await manager.send_message(document_id, data)
            if data.get("status") in (
                FileStatus.COMPLETED.value,
                FileStatus.FAILED.value,
            ):
                break
    finally:
        try:
            await pubsub.unsubscribe(f"document_updates:{document_id}")
            await pubsub.close()
        except Exception:
            pass
