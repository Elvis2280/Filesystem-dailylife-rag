import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timezone
from email.utils import format_datetime
from pathlib import PurePath
from urllib.parse import quote

from celery.result import AsyncResult
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_key import is_api_key_valid
from app.core.constant import ALLOWED_UPLOAD_MIME_TYPES
from app.core.database import get_db
from app.core.redis_client import get_async_redis_client
from app.core.websocket_manager import manager
from app.models.document import Document
from app.models.workspace import WorkspaceModel
from app.schemas.document import (
    DocumentStatusResponse,
    DocumentUploadResponse,
    FileConversionPayload,
    FileConversionResponse,
)
from app.services.storage.document import (
    DuplicateDocumentError,
    convert_to_pdf,
    process_document_upload,
)
from app.services.storage.document_preview import (
    PdfPreviewNotFound,
    resolve_pdf_document,
)
from app.services.storage.object_storage import (
    OBJECT_STREAM_CHUNK_SIZE,
    ObjectMetadata,
    ObjectStorageError,
    get_object_stream,
    head_object,
)
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


@dataclass(frozen=True)
class _ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class _InvalidByteRange(ValueError):
    """Raised when a request contains an unsupported or unsatisfiable range."""


def _parse_range_integer(value: str) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise _InvalidByteRange
    try:
        return int(value)
    except ValueError as exc:
        raise _InvalidByteRange from exc


def _parse_range_header(value: str | None, total_size: int) -> _ByteRange | None:
    if value is None:
        return None
    if not value.startswith("bytes="):
        raise _InvalidByteRange

    range_spec = value[6:].strip()
    if not range_spec or "," in range_spec or "-" not in range_spec:
        raise _InvalidByteRange

    start_text, end_text = (part.strip() for part in range_spec.split("-", 1))
    if total_size <= 0:
        raise _InvalidByteRange

    if not start_text:
        suffix_length = _parse_range_integer(end_text)
        if suffix_length <= 0:
            raise _InvalidByteRange
        return _ByteRange(
            start=max(total_size - suffix_length, 0),
            end=total_size - 1,
        )

    start = _parse_range_integer(start_text)
    if start >= total_size:
        raise _InvalidByteRange

    if not end_text:
        end = total_size - 1
    else:
        end = min(_parse_range_integer(end_text), total_size - 1)

    if end < start:
        raise _InvalidByteRange
    return _ByteRange(start=start, end=end)


def _content_disposition(filename: str) -> str:
    name = PurePath(filename).name or "document.pdf"
    name = name.replace("\r", "_").replace("\n", "_").replace('"', "_")
    if not name.lower().endswith(".pdf"):
        name = f"{PurePath(name).stem or 'document'}.pdf"
    ascii_name = name.encode("ascii", "ignore").decode("ascii") or "document.pdf"
    ascii_name = ascii_name.replace("\\", "_").replace('"', "_")
    encoded_name = quote(name, safe="")
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"


def _preview_headers(
    document: Document,
    metadata: ObjectMetadata,
    content_length: int,
    byte_range: _ByteRange | None,
) -> dict[str, str]:
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Disposition": _content_disposition(document.original_filename),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if byte_range is not None:
        headers["Content-Range"] = (
            f"bytes {byte_range.start}-{byte_range.end}/{metadata.size}"
        )
    if metadata.etag:
        headers["ETag"] = metadata.etag
    if metadata.last_modified:
        last_modified = metadata.last_modified
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        headers["Last-Modified"] = format_datetime(
            last_modified.astimezone(timezone.utc), usegmt=True
        )
    return headers


async def _stream_object(body) -> AsyncIterator[bytes]:
    try:
        while True:
            chunk = await asyncio.to_thread(body.read, OBJECT_STREAM_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        await asyncio.to_thread(body.close)


async def _prepare_pdf_preview(
    document_id: str,
    range_header: str | None,
    db: AsyncSession,
) -> tuple[Document, ObjectMetadata, _ByteRange | None]:
    if not _is_valid_uuid(document_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="document_id must be a valid UUID",
        )

    try:
        pdf_document = await resolve_pdf_document(uuid.UUID(document_id), db)
    except PdfPreviewNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="A PDF representation is not available for this document",
        ) from exc

    try:
        metadata = await asyncio.to_thread(head_object, pdf_document.storage_key)
    except (ObjectStorageError, ValueError) as exc:
        logger.error(
            "PDF object unavailable document_id=%s storage_key=%s",
            pdf_document.id,
            pdf_document.storage_key,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The PDF object is temporarily unavailable",
        ) from exc

    if metadata.size != pdf_document.size:
        logger.error(
            "PDF metadata mismatch document_id=%s storage_key=%s "
            "db_size=%s object_size=%s",
            pdf_document.id,
            pdf_document.storage_key,
            pdf_document.size,
            metadata.size,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The PDF object metadata is inconsistent",
        )

    try:
        byte_range = _parse_range_header(range_header, metadata.size)
    except _InvalidByteRange as exc:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="The requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{metadata.size}"},
        ) from exc
    return pdf_document, metadata, byte_range


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
    except DuplicateDocumentError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "A document with the same content already exists in this workspace.",
                "document_id": str(e.existing_document_id),
            },
        ) from e
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
    "/documents/{document_id}/pdf",
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
)
async def get_document_pdf(
    document_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    db: AsyncSession = Depends(get_db),
):
    """Stream the canonical PDF for a document from Garage."""

    pdf_document, metadata, byte_range = await _prepare_pdf_preview(
        document_id, range_header, db
    )
    object_range = f"bytes={byte_range.start}-{byte_range.end}" if byte_range else None
    try:
        body = await asyncio.to_thread(
            get_object_stream,
            pdf_document.storage_key,
            object_range,
        )
    except (ObjectStorageError, ValueError) as exc:
        logger.error(
            "PDF object stream failed document_id=%s storage_key=%s",
            pdf_document.id,
            pdf_document.storage_key,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The PDF object is temporarily unavailable",
        ) from exc

    content_length = byte_range.length if byte_range else metadata.size
    headers = _preview_headers(pdf_document, metadata, content_length, byte_range)
    return StreamingResponse(
        _stream_object(body),
        status_code=status.HTTP_206_PARTIAL_CONTENT
        if byte_range
        else status.HTTP_200_OK,
        media_type="application/pdf",
        headers=headers,
    )


@router.head(
    "/documents/{document_id}/pdf",
    response_class=Response,
)
async def head_document_pdf(
    document_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    db: AsyncSession = Depends(get_db),
):
    """Return canonical PDF metadata without opening the Garage body."""

    pdf_document, metadata, byte_range = await _prepare_pdf_preview(
        document_id, range_header, db
    )
    content_length = byte_range.length if byte_range else metadata.size
    return Response(
        status_code=status.HTTP_206_PARTIAL_CONTENT
        if byte_range
        else status.HTTP_200_OK,
        media_type="application/pdf",
        headers=_preview_headers(pdf_document, metadata, content_length, byte_range),
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

    query_result = await db.execute(
        select(Document, WorkspaceModel.name)
        .join(WorkspaceModel, WorkspaceModel.id == Document.workspace_id)
        .where(Document.id == document_id)
    )
    document_row = query_result.one_or_none()
    if document_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found in database.",
        )
    document, workspace_name = document_row

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
        original_filename=document.original_filename,
        workspace_name=workspace_name,
        task_id=task_id,
        status=task_state,
        document_record_status=document.status,
        result=result_payload,
        error=error,
        message=message,
    )


@router.websocket("/documents/{document_id}/ws")
async def websocket_document_status(websocket: WebSocket, document_id: str):
    candidate_keys = (
        websocket.headers.get("X-API-Key"),
        websocket.query_params.get("api_key"),
    )
    if not any(is_api_key_valid(candidate) for candidate in candidate_keys):
        await websocket.accept()
        await websocket.close(code=1008, reason="Missing or invalid API key")
        return

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
            converted_file_path=converted_metadata.storage_key,
            converted_mime_type=converted_metadata.mime_type,
            converted_to_extension=converted_metadata.file_extension or "pdf",
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
