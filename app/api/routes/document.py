import json
import logging
import uuid
from pathlib import Path

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
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constant import ALLOWED_UPLOAD_MIME_TYPES
from app.core.database import get_db
from app.core.redis_client import get_async_redis_client
from app.core.websocket_manager import manager
from app.models.document import Document
from app.models.file_conversions import FileConversionModel
from app.models.workspace import WorkspaceModel
from app.schemas.document import (
    DocumentStatusResponse,
    DocumentUploadResponse,
    FileConversionPayload,
    FileConversionResponse,
)
from app.services.storage.document import convert_to_pdf, process_document_upload
from app.services.websocket.document_status import stream_document_status
from workers.celery_app import celery_app

logger = logging.getLogger("memory_rag.routes.document")
router = APIRouter(prefix="/api/v1", tags=["documents"])


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


@router.post(
    "/documents/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_document(
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not _is_valid_uuid(workspace_id):
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
        select(WorkspaceModel).where(WorkspaceModel.id == workspace_id)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found",
        )

    try:
        document, task_id = await process_document_upload(str(workspace.id), file, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {e}",
        )

    return DocumentUploadResponse(
        document_id=str(document.id),
        task_id=task_id,
        workspace_id=workspace_id,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        stored_filename=document.stored_filename,
        page_count=document.page_count,
        status=document.status,
        message="File uploaded and queued for OCR processing.",
    )


@router.get(
    "/documents/{document_id}/status",
    response_model=DocumentStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    if not _is_valid_uuid(document_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_id must be a valid UUID",
        )

    query_result = await db.execute(select(Document).where(Document.id == document_id))
    document = query_result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database.",
        )

    redis_async = await get_async_redis_client()
    task_id = await redis_async.get(f"document_task:{document_id}")
    if not task_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active task found for document {document_id}. The task may have expired or not been submitted.",
        )

    task = AsyncResult(task_id, app=celery_app)
    task_state = task.state

    result_payload = None
    error = None
    message = "Task is pending"

    if task_state == "SUCCESS":
        result_payload = None
        query_json = await db.execute(
            select(FileConversionModel).where(
                and_(
                    FileConversionModel.file_id == document_id,
                    FileConversionModel.converted_to_extension == "json",
                )
            )
        )
        json_records = query_json.scalars().all()
        if json_records:
            result_payload = []
            for record in json_records:
                json_path = Path(record.converted_file_path)
                if json_path.exists():
                    with open(json_path) as f:
                        result_payload.append(json.load(f))
        message = "OCR processing completed successfully"
    elif task_state == "PROGRESS":
        meta = task.info or {}
        message = f"Task in progress: {meta.get('stage', 'unknown')}"
    elif task_state == "FAILURE":
        error = str(task.info) if task.info else "Unknown error"
        message = f"Task failed: {error}"

        if document.status != "failed":
            document.status = "failed"
            await db.commit()

    return DocumentStatusResponse(
        document_id=document_id,
        task_id=task_id,
        status=task_state,
        document_record_status=document.status,
        result=result_payload,
        error=error,
        message=message,
    )


@router.websocket("/documents/{document_id}/ws")
async def websocket_document_status(websocket: WebSocket, document_id: str):
    await manager.connect(document_id, websocket)
    try:
        await stream_document_status(document_id)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(document_id)


@router.post(
    "/documents/convert-doc-to-pdf",
    response_model=FileConversionResponse,
    status_code=status.HTTP_200_OK,
)
async def convert_document(
    payload: FileConversionPayload,
    db: AsyncSession = Depends(get_db),
):
    doc_id = payload.file_id
    if not _is_valid_uuid(doc_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_id must be a valid UUID",
        )

    try:
        converted_metadata = await convert_to_pdf(doc_id, db)
        return FileConversionResponse(
            file_id=doc_id,
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
