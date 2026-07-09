"""WebSocket streaming for document processing status.

Subscribes to Redis pub/sub channel `document_updates:{document_id}`
and relays messages to the WebSocket client until the task completes
or fails.
"""

import json
import logging

from app.core.constant import FileStatus
from app.core.redis_client import redis_client
from app.core.websocket_manager import manager

logger = logging.getLogger("memory_rag.ws.document_status")


async def stream_document_status(document_id: str) -> None:
    pubsub = redis_client.pubsub()
    pubsub.subscribe(f"document_updates:{document_id}")
    try:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            await manager.send(document_id, data)
            if data.get("status") in (
                FileStatus.COMPLETED.value,
                FileStatus.FAILED.value,
            ):
                break
    finally:
        pubsub.unsubscribe(f"document_updates:{document_id}")
        pubsub.close()
