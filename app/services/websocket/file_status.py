"""WebSocket file status streaming service.

Handles real-time progress updates for file processing via Redis pub/sub,
including task state catch-up from Celery AsyncResult, heartbeat
coordination, and message relay to connected WebSocket clients.
"""

import asyncio
import json
import logging
from datetime import datetime

from celery.result import AsyncResult

from app.core.constant import FilePipelineStage
from app.core.redis_client import get_async_redis_client
from app.core.websocket_manager import manager
from workers.celery_app import celery_app

logger = logging.getLogger("memory_rag.websocket.file_status")

# Map of worker `update_state(meta={"stage": ...})` values to FilePipelineStage
# enum entries, used to reconstruct the current pipeline step from a
# Celery AsyncResult when the WebSocket connects mid-task.
_STAGE_NAME_MAP: dict[str, FilePipelineStage] = {
    "pdf_conversion": FilePipelineStage.PDF_CONVERSION,
    "image_conversion": FilePipelineStage.IMAGE_CONVERSION,
    "ocr_processing": FilePipelineStage.OCR_PROCESSING,
}


async def stream_file_status(file_id: str) -> None:
    """Stream file processing status to the connected WebSocket client.

    Subscribes to the Redis pub/sub channel for real-time updates,
    sends catch-up state from Celery AsyncResult if the task is
    already in progress, and relays pub/sub messages until the
    task completes or the client disconnects.

    Must be called after manager.connect(file_id, websocket).
    The caller is responsible for calling manager.disconnect(file_id)
    once this coroutine returns, to clean up the connection state.

    Args:
        file_id: UUID of the file being processed.
    """
    pubsub = None
    heartbeat_task: asyncio.Task | None = None

    try:
        redis_async = await get_async_redis_client()
        task_id = await redis_async.get(f"file_task:{file_id}")
        if not task_id:
            await _send_final_status(
                file_id,
                status="FAILURE",
                step="0/4",
                stage="failed",
                message="No task found for this file",
            )
            return

        task = AsyncResult(task_id, app=celery_app)
        task_state = _safe_task_state(task)

        if task_state == "SUCCESS":
            result = task.result
            total_pages = len(result) if isinstance(result, list) else 0
            await _send_final_status(
                file_id,
                status="SUCCESS",
                step="4/4",
                stage="completed",
                message="Processing completed successfully!",
                total_pages=total_pages,
                result=result,
            )
            return

        if task_state == "FAILURE":
            error_msg = str(task.info) if task.info else "Unknown error"
            await _send_final_status(
                file_id,
                status="FAILURE",
                step="0/4",
                stage="failed",
                message=error_msg,
                error=error_msg,
            )
            return

        pubsub = redis_async.pubsub()
        await pubsub.subscribe(f"file_updates:{file_id}")

        # Catch-up: after subscribing, re-check task state so the client gets
        # the current pipeline stage immediately, even if intermediate
        # pub/sub messages were published before the subscription.
        task_state = _safe_task_state(task)
        if task_state == "PROGRESS":
            meta = task.info or {}
            stage_name = meta.get("stage")
            stage = _STAGE_NAME_MAP.get(stage_name, FilePipelineStage.PENDING)
            await manager.send_message(
                file_id,
                {
                    "status": "PROGRESS",
                    "step": stage.step,
                    "stage": stage.value,
                    "message": stage.message,
                    "file_id": file_id,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            manager.update_step(file_id, stage.step)
        else:
            await manager.send_message(
                file_id,
                {
                    "status": "PENDING",
                    "step": "0/4",
                    "stage": "pending",
                    "message": "Waiting for task to start...",
                    "file_id": file_id,
                    "timestamp": datetime.now().isoformat(),
                },
            )

        heartbeat_task = asyncio.create_task(manager.heartbeat(file_id))

        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue

            data = json.loads(message["data"])
            await manager.send_message(file_id, data)

            step = data.get("step")
            if step:
                manager.update_step(file_id, step)

            if data.get("status") in ["SUCCESS", "FAILURE"]:
                break

    except Exception as e:
        logger.exception("WebSocket streaming error for file %s", file_id)
        await _send_final_status(
            file_id,
            status="ERROR",
            step="0/4",
            stage="error",
            message=f"WebSocket error: {e}",
        )
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        if pubsub is not None:
            try:
                await pubsub.unsubscribe()
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass


async def _send_final_status(file_id: str, **kwargs: object) -> None:
    """Send a final status message with a timestamp to the WebSocket client."""
    await manager.send_message(
        file_id,
        {
            "file_id": file_id,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        },
    )


def _safe_task_state(task: AsyncResult) -> str:
    """Return the Celery task state, defaulting to FAILURE on access errors."""
    try:
        return task.state
    except (ValueError, KeyError):
        return "FAILURE"
