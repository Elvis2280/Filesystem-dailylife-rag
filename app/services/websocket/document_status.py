"""WebSocket streaming for document processing status.

Subscribes to Redis pub/sub channel `document_updates:{document_id}`
and relays messages to the WebSocket client until the task completes
or fails.
"""

import asyncio
import json
import logging

from app.core.constant import FileStatus
from app.core.redis_client import get_async_redis_client
from app.core.websocket_manager import manager

logger = logging.getLogger("memory_rag.ws.document_status")


def _send_current_state_sync(document_id: str) -> dict | None:
    """Read the document's current state from the DB (sync, runs in a thread)."""
    from app.core.database import get_sync_db
    from app.models.document import Document
    from app.models.document_history import DocumentHistoryModel

    with get_sync_db() as db:
        history = (
            db.query(DocumentHistoryModel)
            .filter(DocumentHistoryModel.document_id == document_id)
            .order_by(DocumentHistoryModel.created_at.desc())
            .first()
        )
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
        doc = db.query(Document).filter_by(id=document_id).first()
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
    """Run the sync DB query in a thread and send the result to the WebSocket."""
    state = await asyncio.to_thread(_send_current_state_sync, document_id)
    if state is not None:
        await manager.send_message(document_id, state)
    return state


async def stream_document_status(document_id: str) -> None:
    # Send current state first so the client immediately knows the document status
    current_state = None
    try:
        current_state = await _send_current_state(document_id)
    except Exception as e:
        logger.warning("Failed to send current state for %s: %s", document_id, e)

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
