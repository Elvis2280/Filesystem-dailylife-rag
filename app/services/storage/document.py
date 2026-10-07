"""Document upload and Garage-backed persistence services."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path

import fitz
from fastapi import UploadFile
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constant import FilePipelineStage
from app.core.redis_client import redis_client
from app.models.document import Document
from app.models.document_event import DocumentEventModel
from app.services.ocr.utils import build_libreoffice_command
from app.services.storage.file_metadata import (
    converted_document_key,
    original_document_key,
    sha256_file,
)
from app.services.storage.object_storage import (
    delete_object,
    download_file,
    object_exists,
    put_file,
)


class DuplicateDocumentError(ValueError):
    """Raised when the same original file already exists in a workspace."""

    def __init__(self, existing_document_id: uuid.UUID):
        super().__init__(f"Document already exists: {existing_document_id}")
        self.existing_document_id = existing_document_id


def _count_pdf_pages(path: Path) -> int:
    pdf = fitz.open(str(path))
    try:
        return pdf.page_count
    finally:
        pdf.close()


async def process_document_upload(
    workspace_id: str,
    file: UploadFile,
    db: AsyncSession,
) -> tuple[Document, str]:
    document_id = uuid.uuid4()
    workspace_uuid = uuid.UUID(workspace_id)
    uploaded_name = Path(file.filename or "unnamed").name
    ext = uploaded_name.rsplit(".", 1)[-1].lower() if "." in uploaded_name else ""
    mime_type = file.content_type or "application/octet-stream"
    is_pdf = mime_type == "application/pdf"
    stored_filename = (
        f"{document_id}_original.{ext}" if ext else f"{document_id}_original"
    )

    Path(settings.TEMP_PATH).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"upload-{document_id}-",
        dir=settings.TEMP_PATH,
    ) as temp_dir:
        file_path = Path(temp_dir) / stored_filename

        def _sync_copy() -> None:
            with file_path.open("wb") as output:
                shutil.copyfileobj(file.file, output)

        await asyncio.to_thread(_sync_copy)
        file_size = file_path.stat().st_size
        checksum = await asyncio.to_thread(sha256_file, file_path)

        duplicate_result = await db.execute(
            select(Document).where(
                and_(
                    Document.workspace_id == workspace_uuid,
                    Document.parent_document_id.is_(None),
                    Document.file_role == "original",
                    Document.checksum_sha256 == checksum,
                )
            )
        )
        existing = duplicate_result.scalar_one_or_none()
        if existing:
            raise DuplicateDocumentError(existing.id)

        page_count: int | None = None
        if is_pdf:
            try:
                page_count = await asyncio.to_thread(_count_pdf_pages, file_path)
            except Exception as exc:
                raise ValueError(
                    f"Could not read PDF (file may be corrupt or encrypted): {exc}"
                ) from exc
        elif mime_type in {"image/png", "image/jpeg", "image/webp"}:
            page_count = 1

        object_key = original_document_key(
            workspace_uuid,
            document_id,
            stored_filename,
        )
        await asyncio.to_thread(put_file, file_path, object_key, mime_type)

    document = Document(
        id=document_id,
        workspace_id=workspace_uuid,
        file_role="original",
        original_filename=uploaded_name,
        stored_filename=stored_filename,
        storage_key=object_key,
        storage_area="workspace",
        mime_type=mime_type,
        file_extension=ext or None,
        page_count=page_count,
        size=file_size,
        checksum_sha256=checksum,
    )
    db.add(document)
    db.add_all(
        [
            DocumentEventModel(
                document_id=document_id,
                workspace_id=workspace_uuid,
                status="file_uploaded",
                stage=FilePipelineStage.UPLOAD.value,
                step=FilePipelineStage.UPLOAD.step,
                message="File received by the upload endpoint",
            ),
            DocumentEventModel(
                document_id=document_id,
                workspace_id=workspace_uuid,
                status="stored_in_object_storage",
                stage=FilePipelineStage.OBJECT_STORAGE.value,
                step=FilePipelineStage.OBJECT_STORAGE.step,
                message="Original file persisted in Garage",
            ),
        ]
    )
    try:
        await db.commit()
        await db.refresh(document)
    except Exception:
        await db.rollback()
        await asyncio.to_thread(delete_object, object_key)
        raise

    from workers.tasks.file_pipeline import (
        process_file_upload as dispatch_pipeline_task,
    )

    task = dispatch_pipeline_task.delay(str(document_id))
    redis_client.setex(f"document_task:{document_id}", 1800, task.id)
    return document, task.id


async def convert_to_pdf(document_id: str, db_session: AsyncSession) -> Document:
    result = await db_session.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise ValueError(f"Document with ID {document_id} not found in database.")
    if document.file_role != "original":
        raise ValueError("Only original documents can be converted to PDF.")
    if document.mime_type == "application/pdf":
        return document

    existing_result = await db_session.execute(
        select(Document).where(
            Document.parent_document_id == document.id,
            Document.file_role == "converted_pdf",
        )
    )
    existing_pdf = existing_result.scalar_one_or_none()
    if existing_pdf and await asyncio.to_thread(
        object_exists, existing_pdf.storage_key
    ):
        return existing_pdf

    converted_id = existing_pdf.id if existing_pdf else uuid.uuid4()
    object_key = converted_document_key(
        document.workspace_id,
        document.id,
        converted_id,
    )
    Path(settings.TEMP_PATH).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"convert-{document.id}-",
        dir=settings.TEMP_PATH,
    ) as temp_dir:
        output_dir = Path(temp_dir)
        input_path = output_dir / document.stored_filename
        await asyncio.to_thread(download_file, document.storage_key, input_path)
        process = await asyncio.create_subprocess_exec(
            *build_libreoffice_command(str(input_path), str(output_dir)),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed with return code {process.returncode}. "
                f"stderr: {stderr.decode().strip()}"
            )

        expected_pdf = output_dir / input_path.with_suffix(".pdf").name
        if not expected_pdf.exists():
            raise RuntimeError(
                f"Expected converted PDF was not generated. "
                f"stderr: {stderr.decode().strip()}, stdout: {stdout.decode().strip()}"
            )
        converted_size = expected_pdf.stat().st_size
        converted_checksum = await asyncio.to_thread(sha256_file, expected_pdf)
        converted_pages = await asyncio.to_thread(_count_pdf_pages, expected_pdf)
        await asyncio.to_thread(
            put_file,
            expected_pdf,
            object_key,
            "application/pdf",
        )

    converted = existing_pdf or Document(
        id=converted_id,
        workspace_id=document.workspace_id,
        parent_document_id=document.id,
        file_role="converted_pdf",
        original_filename=f"{Path(document.original_filename).stem}.pdf",
        stored_filename=f"{converted_id}.pdf",
        storage_key=object_key,
        storage_area="workspace",
        mime_type="application/pdf",
        file_extension="pdf",
    )
    converted.storage_key = object_key
    converted.size = converted_size
    converted.checksum_sha256 = converted_checksum
    converted.page_count = converted_pages
    converted.status = "completed"
    converted.last_error = None
    document.page_count = converted_pages
    db_session.add(converted)
    db_session.add(
        DocumentEventModel(
            document_id=document.id,
            workspace_id=document.workspace_id,
            status="file_conversion_finished",
            stage=FilePipelineStage.PDF_CONVERSION.value,
            step=FilePipelineStage.PDF_CONVERSION.step,
            message=f"Converted PDF persisted in Garage as {object_key}",
        )
    )
    try:
        await db_session.commit()
        await db_session.refresh(converted)
    except Exception:
        await db_session.rollback()
        await asyncio.to_thread(delete_object, object_key)
        raise
    return converted
