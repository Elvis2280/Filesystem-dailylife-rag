import logging
import uuid

from celery.result import AsyncResult
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constant import ALLOWED_UPLOAD_MIME_TYPES
from app.core.database import get_db
from app.core.redis_client import get_async_redis_client
from app.core.websocket_manager import manager
from app.models.file import FileModel
from app.models.workspace import WorkspaceModel
from app.schemas.file import (
    FileConversionPayload,
    FileConversionResponse,
    FileStatusResponse,
    FileUploadResponse,
)
from app.services.storage.file import convert_to_pdf, process_file_upload
from app.services.websocket.file_status import stream_file_status
from workers.celery_app import celery_app

logger = logging.getLogger("memory_rag.routes.file")
router = APIRouter(prefix="/api/v1", tags=["files"])


def _is_valid_uuid(value: str) -> bool:
    """Return True if value is a valid UUID string."""
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


@router.post(
    "/files/upload",
    response_model=FileUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_file(
    workspace_storage_key: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file and dispatch async OCR processing.

    Validates the workspace, saves the file to disk, creates a
    database record, and dispatches a Celery task for processing.
    """
    # TODO: Move this validation to validators.py
    if not _is_valid_uuid(workspace_storage_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace_id must be a valid UUID",
        )

    if file.content_type not in ALLOWED_UPLOAD_MIME_TYPES:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_MIME_TYPES))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{file.content_type}' not allowed. Supported types: {allowed}",
        )

    result = await db.execute(
        select(WorkspaceModel).filter_by(storage_key=workspace_storage_key)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_storage_key}' not found",
        )

    try:
        file_record, task_id = await process_file_upload(str(workspace.id), file, db)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {e}",
        )

    return FileUploadResponse(
        file_id=str(file_record.id),
        task_id=task_id,
        workspace_id=workspace_storage_key,
        file_extension=file_record.file_extension,
        original_filename=file_record.original_filename,
        mime_type=file_record.mime_type,
        status=file_record.status,
        message="File uploaded and queued for OCR processing.",
    )


@router.get(
    "/files/{file_id}/status",
    response_model=FileStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_file_status(
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    if not _is_valid_uuid(file_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_id must be a valid UUID",
        )

    query_result = await db.execute(select(FileModel).where(FileModel.id == file_id))
    file_record = query_result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with ID {file_id} not found in database.",
        )

    # Retrieve Celery task ID from Redis via file_id
    redis_async = await get_async_redis_client()
    task_id = await redis_async.get(f"file_task:{file_id}")
    if not task_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active task found for file {file_id}. The task may have expired or not been submitted.",
        )

    task = AsyncResult(task_id, app=celery_app)
    task_state = task.state

    result = None
    error = None
    message = "Task is pending"

    if task_state == "SUCCESS":
        result = task.result
        message = "OCR processing completed successfully"
    elif task_state == "PROGRESS":
        meta = task.info or {}
        message = f"Task in progress: {meta.get('stage', 'unknown')}"
    elif task_state == "FAILURE":
        error = str(task.info) if task.info else "Unknown error"
        message = f"Task failed: {error}"

        if file_record.status != "failed":
            file_record.status = "failed"
            await db.commit()

    return FileStatusResponse(
        file_id=file_id,
        task_id=task_id,
        status=task_state,
        file_record_status=file_record.status,
        result=result,
        error=error,
        message=message,
    )


@router.websocket("/files/{file_id}/ws")
async def websocket_file_status(websocket: WebSocket, file_id: str):
    """WebSocket endpoint for real-time file processing status.

    Delegates the streaming logic to stream_file_status() in the
    WebSocket service layer, which subscribes to Redis pub/sub and
    relays progress updates until the task completes.
    """
    await manager.connect(file_id, websocket)
    try:
        await stream_file_status(file_id)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(file_id)


@router.post(
    "/files/convert-doc-to-pdf",
    response_model=FileConversionResponse,
    status_code=status.HTTP_200_OK,
)
async def convert_file(
    payload: FileConversionPayload,
    db: AsyncSession = Depends(get_db),
):
    file_id = payload.file_id
    if not _is_valid_uuid(file_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_id must be a valid UUID",
        )

    try:
        converted_metadata = await convert_to_pdf(file_id, db)
        return FileConversionResponse(
            file_id=file_id,
            converted_file_path=converted_metadata.converted_file_path,
            converted_mime_type=converted_metadata.converted_mime_type,
            converted_to_extension=converted_metadata.converted_to_extension,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to convert file: {e}",
        )
