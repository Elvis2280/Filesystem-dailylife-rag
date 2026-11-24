import asyncio
import logging
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timezone
from email.utils import format_datetime
from pathlib import Path, PurePath
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import Response, StreamingResponse
from redis.exceptions import RedisError
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_key import is_api_key_valid
from app.core.constant import ALLOWED_UPLOAD_MIME_TYPES, FilePipelineStage, FileStatus
from app.core.database import get_db
from app.core.redis_client import get_async_redis_client, redis_client
from app.models.document import Document
from app.models.document_event import DocumentEventModel
from app.models.document_split import DocumentSplitModel
from app.models.translation import TranslationModel
from app.models.workspace import WorkspaceModel
from app.schemas.document import (
    DocumentHistoryEvent,
    DocumentHistoryResponse,
    DocumentRetryResponse,
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
from app.services.storage.file_metadata import (
    document_object_prefix,
    original_document_key,
    sha256_file,
)
from app.services.storage.object_storage import delete_prefix, put_file
from app.services.rag.qdrant_client import delete_document_embeddings
from app.services.storage.document_preview import (
    PdfPreviewNotFound,
    resolve_pdf_document,
)
from app.services.storage.image_preview import (
    ImagePreviewNotFound,
    resolve_split_image,
)
from app.services.storage.translation_preview import (
    TranslationPreviewNotFound,
    resolve_translation,
)
from app.services.document_status import (
    document_failure_message,
    document_has_recent_activity,
    document_worker_is_active,
    resolve_document_status,
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


def _content_disposition(filename: str, extension: str | None = ".pdf") -> str:
    fallback_name = f"document{extension or ''}"
    name = PurePath(filename).name or fallback_name
    name = name.replace("\r", "_").replace("\n", "_").replace('"', "_")
    if extension and not name.lower().endswith(extension):
        name = f"{PurePath(name).stem or PurePath(fallback_name).stem}{extension}"
    ascii_name = name.encode("ascii", "ignore").decode("ascii") or fallback_name
    ascii_name = ascii_name.replace("\\", "_").replace('"', "_")
    encoded_name = quote(name, safe="")
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"


def _preview_headers(
    filename: str,
    metadata: ObjectMetadata,
    content_length: int,
    byte_range: _ByteRange | None,
    extension: str | None = ".pdf",
) -> dict[str, str]:
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Disposition": _content_disposition(filename, extension),
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


async def _prepare_translation_preview(
    translation_id: str,
    range_header: str | None,
    db: AsyncSession,
) -> tuple[TranslationModel, ObjectMetadata, _ByteRange | None]:
    if not _is_valid_uuid(translation_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="translation_id must be a valid UUID",
        )

    try:
        translation = await resolve_translation(uuid.UUID(translation_id), db)
    except TranslationPreviewNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Translation was not found",
        ) from exc

    try:
        metadata = await asyncio.to_thread(head_object, translation.storage_key)
    except (ObjectStorageError, ValueError) as exc:
        logger.error(
            "Markdown object unavailable translation_id=%s storage_key=%s",
            translation.id,
            translation.storage_key,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The Markdown object is temporarily unavailable",
        ) from exc

    if metadata.size != translation.size:
        logger.error(
            "Markdown metadata mismatch translation_id=%s storage_key=%s "
            "db_size=%s object_size=%s",
            translation.id,
            translation.storage_key,
            translation.size,
            metadata.size,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The Markdown object metadata is inconsistent",
        )

    try:
        byte_range = _parse_range_header(range_header, metadata.size)
    except _InvalidByteRange as exc:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="The requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{metadata.size}"},
        ) from exc
    return translation, metadata, byte_range


async def _prepare_split_image_preview(
    split_id: str,
    range_header: str | None,
    db: AsyncSession,
) -> tuple[DocumentSplitModel, ObjectMetadata, _ByteRange | None]:
    if not _is_valid_uuid(split_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="split_id must be a valid UUID",
        )

    try:
        split = await resolve_split_image(uuid.UUID(split_id), db)
    except ImagePreviewNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Split image was not found",
        ) from exc

    try:
        metadata = await asyncio.to_thread(head_object, split.storage_key)
    except (ObjectStorageError, ValueError) as exc:
        logger.error(
            "Split image object unavailable split_id=%s storage_key=%s",
            split.id,
            split.storage_key,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The split image is temporarily unavailable",
        ) from exc

    if metadata.size != split.size:
        logger.error(
            "Split image metadata mismatch split_id=%s storage_key=%s "
            "db_size=%s object_size=%s",
            split.id,
            split.storage_key,
            split.size,
            metadata.size,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The split image metadata is inconsistent",
        )

    try:
        byte_range = _parse_range_header(range_header, metadata.size)
    except _InvalidByteRange as exc:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="The requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{metadata.size}"},
        ) from exc
    return split, metadata, byte_range


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
    if workspace is None:
        raise HTTPException(
            status_code=404, detail=f"Workspace '{workspace_id}' not found"
        )
    try:
        document, task_id = await process_document_upload(str(workspace.id), file, db)
    except DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A document with the same content already exists in this workspace.",
                "document_id": str(exc.existing_document_id),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


@router.patch("/documents/{document_id}", response_model=DocumentUploadResponse)
async def replace_document(
    document_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Replace a document's source file and rebuild its derived data."""
    if not _is_valid_uuid(document_id):
        raise HTTPException(status_code=400, detail="document_id must be a valid UUID")
    if file.content_type not in ALLOWED_UPLOAD_MIME_TYPES:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_MIME_TYPES))
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type. Supported types: {allowed}"
        )

    result = await db.execute(
        select(Document).where(Document.id == uuid.UUID(document_id)).with_for_update()
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(
            status_code=404, detail=f"Document '{document_id}' not found"
        )
    if document.parent_document_id is not None or document.file_role != "original":
        raise HTTPException(
            status_code=409, detail="Only original documents can be replaced"
        )
    busy_statuses = {
        FileStatus.RETRY_QUEUED.value,
        FileStatus.RETRY_RUNNING.value,
        FileStatus.FILE_PROCESSING.value,
        FileStatus.INDEXING.value,
        "file_uploaded",
        "file_conversion_started",
        "file_conversion_finished",
        "ocr_started",
        "ocr_finished",
        "translation_and_formatting_started",
        "translation_and_formatting_finished",
        "file_process_finished",
        "processing_document_to_pdf",
        "processing_pdf_to_image",
    }
    if document.status in busy_statuses:
        raise HTTPException(
            status_code=409, detail="Document is currently being processed"
        )

    uploaded_name = None
    try:
        uploaded_name = PurePath(file.filename or "unnamed").name
        ext = uploaded_name.rsplit(".", 1)[-1].lower() if "." in uploaded_name else ""
        stored_filename = (
            f"{document.id}_original.{ext}" if ext else f"{document.id}_original"
        )
        with tempfile.TemporaryDirectory(prefix="replace-") as temp_dir:
            source_path = Path(temp_dir) / stored_filename
            with open(source_path, "wb") as output:
                await asyncio.to_thread(shutil.copyfileobj, file.file, output)
            checksum = await asyncio.to_thread(sha256_file, source_path)
            duplicate = await db.execute(
                select(Document.id).where(
                    Document.workspace_id == document.workspace_id,
                    Document.parent_document_id.is_(None),
                    Document.file_role == "original",
                    Document.checksum_sha256 == checksum,
                    Document.id != document.id,
                )
            )
            if duplicate.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail="This content belongs to another document in this workspace",
                )

            object_key = original_document_key(
                document.workspace_id, document.id, stored_filename
            )
            upload_received_at = await db.scalar(select(func.clock_timestamp()))
            await asyncio.to_thread(
                put_file,
                source_path,
                object_key,
                file.content_type or "application/octet-stream",
            )
            try:
                await asyncio.to_thread(
                    delete_document_embeddings,
                    str(document.id),
                    str(document.workspace_id),
                )
                await asyncio.to_thread(
                    delete_prefix,
                    document_object_prefix(document.workspace_id, document.id) + "/",
                )
                await db.execute(
                    update(DocumentEventModel)
                    .where(DocumentEventModel.document_id == document.id)
                    .values(document_split_id=None, translation_id=None)
                )
                await db.refresh(document, ["splits"])
                document.splits.clear()
                document.original_filename = uploaded_name
                document.stored_filename = stored_filename
                document.storage_key = object_key
                document.mime_type = file.content_type or "application/octet-stream"
                document.file_extension = ext or None
                document.size = source_path.stat().st_size
                document.checksum_sha256 = checksum
                document.page_count = (
                    1
                    if document.mime_type in {"image/png", "image/jpeg", "image/webp"}
                    else None
                )
                document.status = "file_uploaded"
                document.attempt_count = 0
                document.last_error = None
                db.add(
                    DocumentEventModel(
                        document_id=document.id,
                        workspace_id=document.workspace_id,
                        status="file_uploaded",
                        stage=FilePipelineStage.UPLOAD.value,
                        step=FilePipelineStage.UPLOAD.step,
                        message="Replacement file received",
                        created_at=upload_received_at,
                    )
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Document replacement failed document_id=%s", document_id)
        raise HTTPException(
            status_code=502,
            detail="Replacement cleanup or storage failed; retry the request",
        ) from exc

    from workers.tasks.file_pipeline import process_file_upload

    task = process_file_upload.delay(str(document.id))
    redis_client.setex(f"document_task:{document.id}", 1800, task.id)
    await db.refresh(document)
    return DocumentUploadResponse(
        document_id=str(document.id),
        task_id=task.id,
        workspace_id=str(document.workspace_id),
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        stored_filename=document.stored_filename,
        page_count=document.page_count,
        status=document.status,
        message="File replaced and queued for processing.",
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
    headers = _preview_headers(
        pdf_document.original_filename,
        metadata,
        content_length,
        byte_range,
    )
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
        headers=_preview_headers(
            pdf_document.original_filename,
            metadata,
            content_length,
            byte_range,
        ),
    )


@router.get(
    "/documents/{translation_id}/markdown",
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
)
async def get_translation_markdown(
    translation_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    db: AsyncSession = Depends(get_db),
):
    """Stream one translated Markdown page from Garage."""

    translation, metadata, byte_range = await _prepare_translation_preview(
        translation_id, range_header, db
    )
    object_range = f"bytes={byte_range.start}-{byte_range.end}" if byte_range else None
    try:
        body = await asyncio.to_thread(
            get_object_stream,
            translation.storage_key,
            object_range,
        )
    except (ObjectStorageError, ValueError) as exc:
        logger.error(
            "Markdown object stream failed translation_id=%s storage_key=%s",
            translation.id,
            translation.storage_key,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The Markdown object is temporarily unavailable",
        ) from exc

    content_length = byte_range.length if byte_range else metadata.size
    headers = _preview_headers(
        translation.filename,
        metadata,
        content_length,
        byte_range,
        extension=".md",
    )
    return StreamingResponse(
        _stream_object(body),
        status_code=status.HTTP_206_PARTIAL_CONTENT
        if byte_range
        else status.HTTP_200_OK,
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


@router.head(
    "/documents/{translation_id}/markdown",
    response_class=Response,
)
async def head_translation_markdown(
    translation_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    db: AsyncSession = Depends(get_db),
):
    """Return translated Markdown metadata without opening the Garage body."""

    translation, metadata, byte_range = await _prepare_translation_preview(
        translation_id, range_header, db
    )
    content_length = byte_range.length if byte_range else metadata.size
    return Response(
        status_code=status.HTTP_206_PARTIAL_CONTENT
        if byte_range
        else status.HTTP_200_OK,
        media_type="text/markdown; charset=utf-8",
        headers=_preview_headers(
            translation.filename,
            metadata,
            content_length,
            byte_range,
            extension=".md",
        ),
    )


@router.get(
    "/documents/{split_id}/images",
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
)
async def get_split_image(
    split_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    db: AsyncSession = Depends(get_db),
):
    """Stream one split image from Garage."""

    split, metadata, byte_range = await _prepare_split_image_preview(
        split_id, range_header, db
    )
    object_range = f"bytes={byte_range.start}-{byte_range.end}" if byte_range else None
    try:
        body = await asyncio.to_thread(
            get_object_stream,
            split.storage_key,
            object_range,
        )
    except (ObjectStorageError, ValueError) as exc:
        logger.error(
            "Split image object stream failed split_id=%s storage_key=%s",
            split.id,
            split.storage_key,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The split image is temporarily unavailable",
        ) from exc

    content_length = byte_range.length if byte_range else metadata.size
    headers = _preview_headers(
        split.filename,
        metadata,
        content_length,
        byte_range,
        extension=None,
    )
    return StreamingResponse(
        _stream_object(body),
        status_code=status.HTTP_206_PARTIAL_CONTENT
        if byte_range
        else status.HTTP_200_OK,
        media_type=split.file_type,
        headers=headers,
    )


@router.head(
    "/documents/{split_id}/images",
    response_class=Response,
)
async def head_split_image(
    split_id: str,
    range_header: str | None = Header(default=None, alias="Range"),
    db: AsyncSession = Depends(get_db),
):
    """Return split image metadata without opening the Garage body."""

    split, metadata, byte_range = await _prepare_split_image_preview(
        split_id, range_header, db
    )
    content_length = byte_range.length if byte_range else metadata.size
    return Response(
        status_code=status.HTTP_206_PARTIAL_CONTENT
        if byte_range
        else status.HTTP_200_OK,
        media_type=split.file_type,
        headers=_preview_headers(
            split.filename,
            metadata,
            content_length,
            byte_range,
            extension=None,
        ),
    )


@router.post(
    "/documents/{document_id}/retry",
    response_model=DocumentRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> DocumentRetryResponse:
    if not _is_valid_uuid(document_id):
        raise HTTPException(status_code=400, detail="document_id must be a valid UUID")
    doc_id = uuid.UUID(document_id)
    document = await db.scalar(
        select(Document).where(Document.id == doc_id).with_for_update()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.file_role != "original" or document.parent_document_id is not None:
        raise HTTPException(
            status_code=409, detail="Only original documents can be retried"
        )

    latest_event = await db.scalar(
        select(DocumentEventModel)
        .where(DocumentEventModel.document_id == doc_id)
        .order_by(DocumentEventModel.created_at.desc(), DocumentEventModel.id.desc())
        .limit(1)
    )
    if await document_worker_is_active(db, document):
        raise HTTPException(status_code=409, detail="Document is still being processed")

    effective_status, worker_stopped = await resolve_document_status(
        db, document, latest_event
    )
    if effective_status == FileStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409, detail="Completed documents cannot be retried"
        )
    is_saved_failure = document.status == FileStatus.FAILED.value or (
        latest_event is not None and latest_event.status == FileStatus.FAILED.value
    )
    has_recent_activity = document_has_recent_activity(document, latest_event)
    if not is_saved_failure and not worker_stopped and has_recent_activity:
        raise HTTPException(
            status_code=409,
            detail="Document recently reported progress and may still be running",
        )
    if not is_saved_failure and not worker_stopped:
        raise HTTPException(
            status_code=409,
            detail=f"Document is not failed or abandoned (current status: {document.status})",
        )

    if effective_status == FileStatus.FAILED.value and (
        latest_event is None or latest_event.status != FileStatus.FAILED.value
    ):
        db.add(
            DocumentEventModel(
                document_id=doc_id,
                workspace_id=document.workspace_id,
                status=FileStatus.FAILED.value,
                stage=latest_event.stage if latest_event else None,
                step=latest_event.step if latest_event else None,
                message=document_failure_message(
                    document, latest_event, worker_stopped
                ),
                page_number=latest_event.page_number if latest_event else None,
                total_pages=document.page_count,
            )
        )

    # Older failures used a generic stage. Look back to their last real step.
    processing_stages = {
        stage.value
        for stage in FilePipelineStage
        if stage
        not in (
            FilePipelineStage.PENDING,
            FilePipelineStage.FAILED,
            FilePipelineStage.COMPLETED,
        )
    }
    resume_from = (
        await db.scalar(
            select(DocumentEventModel.stage)
            .where(
                DocumentEventModel.document_id == doc_id,
                DocumentEventModel.stage.in_(processing_stages),
            )
            .order_by(
                DocumentEventModel.created_at.desc(), DocumentEventModel.id.desc()
            )
            .limit(1)
        )
        or FilePipelineStage.OBJECT_STORAGE.value
    )

    task_id = uuid.uuid4()
    document.status = FileStatus.RETRY_QUEUED.value
    document.last_error = None
    db.add(
        DocumentEventModel(
            id=task_id,
            document_id=doc_id,
            workspace_id=document.workspace_id,
            status=FileStatus.RETRY_QUEUED.value,
            stage=FilePipelineStage.PENDING.value,
            step=FilePipelineStage.PENDING.step,
            message="Retry queued. Checking saved progress before resuming.",
        )
    )
    try:
        await db.flush()
        # Use the broker even in eager mode. The worker waits on this row lock
        # and verifies the committed queue event before it touches any files.
        await asyncio.to_thread(
            celery_app.send_task,
            "workers.tasks.retry_document",
            args=[str(doc_id), resume_from],
            task_id=str(task_id),
            retry=False,
            ignore_result=False,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("Could not queue retry for document %s", doc_id)
        raise HTTPException(
            status_code=503, detail="Could not queue document retry"
        ) from exc

    return DocumentRetryResponse(document_id=str(doc_id), task_id=str(task_id))


@router.get(
    "/documents/{document_id}/status",
    response_model=DocumentStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    if not _is_valid_uuid(document_id):
        raise HTTPException(status_code=400, detail="document_id must be a valid UUID")
    doc_id = uuid.UUID(document_id)
    query_result = await db.execute(
        select(Document, WorkspaceModel.name)
        .join(WorkspaceModel, WorkspaceModel.id == Document.workspace_id)
        .where(Document.id == doc_id)
    )
    document_row = query_result.one_or_none()
    if document_row is None:
        raise HTTPException(
            status_code=404, detail=f"Document with ID {doc_id} not found"
        )
    document, workspace_name = document_row

    events = (
        select(DocumentEventModel)
        .where(DocumentEventModel.document_id == doc_id)
        .order_by(DocumentEventModel.created_at.desc(), DocumentEventModel.id.desc())
        .limit(1)
    )
    latest = await db.scalar(events)
    retry_event = await db.scalar(
        events.where(DocumentEventModel.status == FileStatus.RETRY_QUEUED.value)
    )
    task_id = str(retry_event.id) if retry_event is not None else None
    if task_id is None:
        try:
            redis_async = await get_async_redis_client()
            task_id = await redis_async.get(f"document_task:{doc_id}")
        except RedisError:
            logger.warning("Task ID unavailable in Redis for document %s", doc_id)

    error = None
    message = (
        latest.message if latest and latest.message else "Document is being processed"
    )
    effective_status, worker_stopped = await resolve_document_status(
        db, document, latest
    )
    if effective_status == FileStatus.FAILED.value:
        task_state = "FAILURE"
        error = document_failure_message(document, latest, worker_stopped)
        message = error
    elif effective_status == FileStatus.COMPLETED.value:
        task_state = "SUCCESS"
        message = "Document processing and indexing completed"
    elif effective_status in (
        FileStatus.FILE_UPLOADED.value,
        FileStatus.RETRY_QUEUED.value,
    ):
        task_state = "PENDING"
    else:
        task_state = "PROGRESS"

    return DocumentStatusResponse(
        document_id=str(doc_id),
        original_filename=document.original_filename,
        workspace_name=workspace_name,
        task_id=task_id,
        status=task_state,
        document_record_status=effective_status,
        error=error,
        message=message,
    )


@router.get("/documents/{document_id}/history", response_model=DocumentHistoryResponse)
async def get_document_history(
    document_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> DocumentHistoryResponse:
    if await db.get(Document, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")

    events = select(DocumentEventModel).where(
        DocumentEventModel.document_id == document_id
    )
    if cursor is not None:
        previous = await db.scalar(events.where(DocumentEventModel.id == cursor))
        if previous is None:
            raise HTTPException(
                status_code=400, detail="Invalid document history cursor"
            )
        events = events.where(
            tuple_(DocumentEventModel.created_at, DocumentEventModel.id)
            < (previous.created_at, previous.id)
        )
    rows = (
        await db.scalars(
            events.order_by(
                DocumentEventModel.created_at.desc(), DocumentEventModel.id.desc()
            ).limit(limit + 1)
        )
    ).all()
    return DocumentHistoryResponse(
        document_id=document_id,
        events=[DocumentHistoryEvent.model_validate(event) for event in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


async def _wait_for_document_disconnect(websocket: WebSocket) -> None:
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass


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

    await websocket.accept()
    stream = asyncio.create_task(
        stream_document_status(document_id, websocket.send_json)
    )
    disconnect = asyncio.create_task(_wait_for_document_disconnect(websocket))
    try:
        done, _ = await asyncio.wait(
            {stream, disconnect}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            task.result()
        if disconnect not in done:
            await websocket.close()
    except WebSocketDisconnect:
        pass
    finally:
        stream.cancel()
        disconnect.cancel()
        await asyncio.gather(stream, disconnect, return_exceptions=True)


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
