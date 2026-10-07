"""Synchronous Garage persistence helpers used by Celery workers."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import fitz
from PIL import Image
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constant import ALLOWED_IMAGE_EXTENSIONS, FilePipelineStage
from app.models.document import Document
from app.models.document_event import DocumentEventModel
from app.models.document_split import DocumentSplitModel
from app.services.ocr.utils import build_libreoffice_command
from app.services.storage.file_metadata import (
    converted_document_key,
    ocr_object_key,
    pipeline_temp_dir,
    sha256_file,
    split_object_key,
)
from app.services.storage.object_storage import (
    delete_object,
    download_file,
    object_exists,
    put_file,
    put_text,
)

logger = logging.getLogger("memory_rag.document_sync")


def _is_pdf(mime_type: str) -> bool:
    return mime_type == "application/pdf"


def _root_document_id(document: Document) -> uuid.UUID:
    return document.parent_document_id or document.id


def _document_splits_query(document_id: str):
    return (
        select(DocumentSplitModel)
        .join(Document, Document.id == DocumentSplitModel.document_id)
        .where(
            or_(
                DocumentSplitModel.document_id == document_id,
                and_(
                    Document.parent_document_id == document_id,
                    Document.file_role == "converted_pdf",
                ),
            )
        )
        .order_by(DocumentSplitModel.page_number)
    )


def _find_processing_document(document_id: str, db_session: Session) -> Document:
    document = db_session.execute(
        select(Document).where(Document.id == document_id)
    ).scalar_one_or_none()
    if not document:
        raise ValueError(f"Document with ID {document_id} not found in database.")
    if document.file_role == "converted_pdf":
        return document
    child = db_session.execute(
        select(Document).where(
            Document.parent_document_id == document.id,
            Document.file_role == "converted_pdf",
        )
    ).scalar_one_or_none()
    return child or document


def _count_pdf_pages(path: Path) -> int:
    pdf = fitz.open(str(path))
    try:
        return pdf.page_count
    finally:
        pdf.close()


def convert_to_pdf(document_id: str, db_session: Session) -> Document:
    document = db_session.execute(
        select(Document).where(Document.id == document_id)
    ).scalar_one_or_none()
    if not document:
        raise ValueError(f"Document with ID {document_id} not found in database.")
    if document.file_role != "original":
        raise ValueError("Only original documents can be converted to PDF.")
    if _is_pdf(document.mime_type):
        return document

    existing = db_session.execute(
        select(Document).where(
            Document.parent_document_id == document.id,
            Document.file_role == "converted_pdf",
        )
    ).scalar_one_or_none()
    if existing and object_exists(existing.storage_key):
        return existing

    converted_id = existing.id if existing else uuid.uuid4()
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
        download_file(document.storage_key, input_path)
        process = subprocess.run(
            build_libreoffice_command(str(input_path), str(output_dir)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed with return code {process.returncode}. "
                f"stderr: {process.stderr.decode().strip()}"
            )

        expected_pdf = output_dir / input_path.with_suffix(".pdf").name
        if not expected_pdf.exists():
            raise RuntimeError(
                f"Expected converted PDF was not generated. "
                f"stderr: {process.stderr.decode().strip()}"
            )
        converted_size = expected_pdf.stat().st_size
        converted_checksum = sha256_file(expected_pdf)
        converted_pages = _count_pdf_pages(expected_pdf)
        put_file(expected_pdf, object_key, "application/pdf")

    converted = existing or Document(
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
        db_session.commit()
        db_session.refresh(converted)
    except Exception:
        db_session.rollback()
        delete_object(object_key)
        raise
    return converted


def convert_to_images(
    document_id: str, db_session: Session
) -> list[DocumentSplitModel]:
    source = _find_processing_document(document_id, db_session)
    if not _is_pdf(source.mime_type):
        raise ValueError(f"Document {document_id} does not resolve to a PDF.")
    root_document_id = _root_document_id(source)
    Path(settings.TEMP_PATH).mkdir(parents=True, exist_ok=True)
    splits: list[DocumentSplitModel] = []
    with tempfile.TemporaryDirectory(
        prefix=f"split-{root_document_id}-",
        dir=settings.TEMP_PATH,
    ) as temp_dir:
        pdf_path = Path(temp_dir) / source.stored_filename
        download_file(source.storage_key, pdf_path)
        pdf_doc = fitz.open(str(pdf_path))
        try:
            for page_index in range(pdf_doc.page_count):
                page_number = page_index + 1
                existing = db_session.execute(
                    select(DocumentSplitModel).where(
                        DocumentSplitModel.document_id == source.id,
                        DocumentSplitModel.page_number == page_number,
                    )
                ).scalar_one_or_none()
                if existing and object_exists(existing.storage_key):
                    splits.append(existing)
                    continue

                object_key = split_object_key(
                    source.workspace_id,
                    root_document_id,
                    source.id,
                    page_number,
                )
                image_path = Path(temp_dir) / f"page-{page_number:04d}.png"
                pixmap = pdf_doc[page_index].get_pixmap(dpi=200)
                image = Image.frombytes(
                    "RGB", (pixmap.width, pixmap.height), pixmap.samples
                )
                image.save(image_path, format="PNG")
                put_file(image_path, object_key, "image/png")
                split = existing or DocumentSplitModel(
                    id=uuid.uuid4(),
                    workspace_id=source.workspace_id,
                    document_id=source.id,
                    page_number=page_number,
                    filename=image_path.name,
                    storage_key=object_key,
                    file_type="image/png",
                    size=image_path.stat().st_size,
                )
                split.filename = image_path.name
                split.storage_key = object_key
                split.file_type = "image/png"
                split.size = image_path.stat().st_size
                split.status = "image_ready"
                split.attempt_count = (split.attempt_count or 0) + 1
                split.last_error = None
                db_session.add(split)
                db_session.flush()
                db_session.add(
                    DocumentEventModel(
                        document_id=root_document_id,
                        workspace_id=source.workspace_id,
                        document_split_id=split.id,
                        status="image_ready",
                        stage=FilePipelineStage.IMAGE_CONVERSION.value,
                        step=FilePipelineStage.IMAGE_CONVERSION.step,
                        message=f"Page {page_number} split persisted in Garage",
                        page_number=page_number,
                        total_pages=pdf_doc.page_count,
                    )
                )
                splits.append(split)
            db_session.commit()
            for split in splits:
                db_session.refresh(split)
        except Exception as exc:
            db_session.rollback()
            raise RuntimeError(
                f"Failed to convert PDF to images for document {document_id}: {exc}"
            ) from exc
        finally:
            pdf_doc.close()
    return splits


def _ensure_image_split(document: Document, db_session: Session) -> DocumentSplitModel:
    existing = db_session.execute(
        select(DocumentSplitModel).where(
            DocumentSplitModel.document_id == document.id,
            DocumentSplitModel.page_number == 1,
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    split = DocumentSplitModel(
        workspace_id=document.workspace_id,
        document_id=document.id,
        page_number=1,
        filename=document.stored_filename,
        storage_key=document.storage_key,
        file_type=document.mime_type,
        size=document.size,
        status="image_ready",
        attempt_count=1,
    )
    db_session.add(split)
    db_session.flush()
    db_session.add(
        DocumentEventModel(
            document_id=_root_document_id(document),
            workspace_id=document.workspace_id,
            document_split_id=split.id,
            status="image_ready",
            stage=FilePipelineStage.IMAGE_CONVERSION.value,
            step=FilePipelineStage.IMAGE_CONVERSION.step,
            message="Original image registered as page 1 split",
            page_number=1,
            total_pages=1,
        )
    )
    db_session.commit()
    db_session.refresh(split)
    return split


def ensure_pdf_in_workspace(document_id: str, db_session: Session) -> Document:
    """Resolve the physical object used by the pipeline without duplicating PDFs."""
    return _find_processing_document(document_id, db_session)


def return_list_images_path(document_id: str, db_session: Session) -> list[str]:
    source = _find_processing_document(document_id, db_session)
    root_document_id = _root_document_id(source)
    if (
        source.file_extension
        and f".{source.file_extension}" in ALLOWED_IMAGE_EXTENSIONS
    ):
        _ensure_image_split(source, db_session)

    splits = db_session.execute(_document_splits_query(document_id)).scalars().all()
    if not splits:
        raise ValueError(f"No page images found for document {document_id}")

    local_dir = (
        pipeline_temp_dir(
            settings.TEMP_PATH,
            source.workspace_id,
            root_document_id,
        )
        / "ocr-inputs"
    )
    if local_dir.exists():
        shutil.rmtree(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    for split in splits:
        suffix = Path(split.filename).suffix or ".png"
        destination = local_dir / f"page-{split.page_number:04d}{suffix}"
        download_file(split.storage_key, destination)
        paths.append(str(destination))
    return paths


def save_ocr_page(
    document_id: str,
    workspace_id: str,
    page_number: int,
    text: str,
    db_session: Session,
) -> DocumentSplitModel:
    split = db_session.execute(
        select(DocumentSplitModel).where(
            DocumentSplitModel.document_id == document_id,
            DocumentSplitModel.page_number == page_number,
        )
    ).scalar_one_or_none()
    if split is None:
        raise ValueError(
            f"Page split {page_number} for document {document_id} was not found."
        )
    source = db_session.execute(
        select(Document).where(Document.id == split.document_id)
    ).scalar_one()
    root_document_id = _root_document_id(source)
    object_key = ocr_object_key(
        workspace_id,
        root_document_id,
        source.id,
        page_number,
    )
    size = put_text(text, object_key)
    split.ocr_storage_key = object_key
    split.ocr_size = size
    split.status = "ocr_completed"
    split.attempt_count = (split.attempt_count or 0) + 1
    split.last_error = None
    db_session.add(
        DocumentEventModel(
            document_id=root_document_id,
            workspace_id=workspace_id,
            document_split_id=split.id,
            status="ocr_completed",
            stage=FilePipelineStage.OCR_PROCESSING.value,
            step=FilePipelineStage.OCR_PROCESSING.step,
            message=f"OCR text for page {page_number} persisted in Garage",
            page_number=page_number,
        )
    )
    db_session.commit()
    db_session.refresh(split)
    return split


def cleanup_pipeline_temp(workspace_id: str, root_document_id: str) -> None:
    temp_dir = pipeline_temp_dir(
        settings.TEMP_PATH,
        workspace_id,
        root_document_id,
    )
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
