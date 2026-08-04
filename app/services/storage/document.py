"""Document upload and persistence service.

Handles the initial document upload flow: saves uploaded files to disk
(workspace files/ for PDFs, temp_storage/ for non-PDFs), captures
page count for PDFs, creates the database record, and dispatches a
Celery OCR task for async processing.
"""

import asyncio
import logging
import uuid
from pathlib import Path

import fitz
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constant import DocumentsType
from app.core.redis_client import redis_client
from app.models.document import Document
from app.models.document_history import DocumentHistoryModel
from app.models.file_conversions import FileConversionModel
from app.services.ocr.utils import build_libreoffice_command
from workers.tasks.file_pipeline import process_file_upload as dispatch_pipeline_task

logger = logging.getLogger("memory_rag.document")


def _count_pdf_pages(path: Path) -> int:
    doc = fitz.open(str(path))
    try:
        return doc.page_count
    finally:
        doc.close()


async def process_document_upload(
    workspace_id: str,
    file: UploadFile,
    db: AsyncSession,
) -> tuple[Document, str]:
    document_id = uuid.uuid4()
    ext = (file.filename.rsplit(".", 1)[-1] or "").lower()
    base_filename = file.filename[: -len(ext) - 1] if ext else file.filename
    is_pdf = file.content_type == "application/pdf"
    stored_filename = (
        f"{document_id}_original.{ext}" if ext else f"{document_id}_original"
    )

    if is_pdf:
        target_dir = Path(settings.workspace_subdir(workspace_id, "files"))
    else:
        target_dir = Path(settings.temp_workspace_path(workspace_id))
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / stored_filename

    def _sync_copy():
        with open(file_path, "wb") as f:
            import shutil

            shutil.copyfileobj(file.file, f)

    await asyncio.to_thread(_sync_copy)

    page_count: int | None = None
    if is_pdf:
        try:
            page_count = await asyncio.to_thread(_count_pdf_pages, file_path)
        except Exception as e:
            file_path.unlink(missing_ok=True)
            raise ValueError(
                f"Could not read PDF (file may be corrupt or encrypted): {e}"
            ) from e

    document = Document(
        id=document_id,
        workspace_id=uuid.UUID(workspace_id),
        original_filename=base_filename,
        stored_filename=stored_filename,
        mime_type=file.content_type or "application/octet-stream",
        page_count=page_count,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    initial_history = DocumentHistoryModel(
        document_id=document_id,
        status="file_uploaded",
        stage="pending",
        step="0/8",
        message="File uploaded, queued for processing",
    )
    db.add(initial_history)
    await db.commit()

    if is_pdf:
        original_record = FileConversionModel(
            file_id=document_id,
            converted_file_path=str(file_path),
            converted_mime_type=file.content_type or "application/pdf",
            converted_to_extension="pdf",
            document_type=DocumentsType.ORIGINAL_FILE.value,
        )
        db.add(original_record)
        await db.commit()

    task = dispatch_pipeline_task.delay(str(document_id))
    redis_client.setex(f"document_task:{document_id}", 1800, task.id)

    return document, task.id


async def convert_to_pdf(
    document_id: str, db_session: AsyncSession
) -> FileConversionModel:
    query_result = await db_session.execute(
        select(Document).where(Document.id == document_id)
    )
    document = query_result.scalar_one_or_none()
    if not document:
        raise ValueError(f"Document with ID {document_id} not found in database.")
    is_pdf = document.mime_type == "application/pdf"

    if is_pdf:
        raise ValueError(
            f"Document with ID {document_id} is already a PDF, cannot convert."
        )

    # Resolve input path from stored_filename + workspace_id
    input_dir = Path(settings.temp_workspace_path(str(document.workspace_id)))
    input_path = (input_dir / document.stored_filename).resolve()

    if not input_path.exists():
        raise ValueError(f"Document file not found on disk: {input_path}")

    output_path = Path(settings.workspace_subdir(str(document.workspace_id), "files"))
    output_path.mkdir(parents=True, exist_ok=True)
    libreoffice_command = build_libreoffice_command(str(input_path), str(output_path))
    proc = await asyncio.create_subprocess_exec(
        *libreoffice_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"LibreOffice conversion failed with return code {proc.returncode}. "
            f"stderr: {stderr.decode().strip()}"
        )

    expected_pdf = output_path / input_path.with_suffix(".pdf").name
    if not expected_pdf.exists():
        raise RuntimeError(
            f"Expected converted PDF not found at {expected_pdf} after LibreOffice conversion. "
            f"stderr: {stderr.decode().strip()}, stdout: {stdout.decode().strip()}"
        )

    converted_pdf_metadata = FileConversionModel(
        file_id=document_id,
        converted_file_path=str(expected_pdf),
        converted_mime_type="application/pdf",
        converted_to_extension="pdf",
        document_type=DocumentsType.CONVERTED_PDF.value,
    )

    db_session.add(converted_pdf_metadata)
    await db_session.commit()
    await db_session.refresh(converted_pdf_metadata)

    return converted_pdf_metadata
