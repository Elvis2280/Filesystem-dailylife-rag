import logging
import shutil
import subprocess
import uuid
from pathlib import Path

import fitz
from PIL import Image
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constant import ALLOWED_IMAGE_EXTENSIONS, DocumentsType, LanguageOptions
from app.models.document import Document
from app.models.file_conversions import FileConversionModel
from app.services.ocr.utils import build_libreoffice_command


def _is_pdf(mime_type: str) -> bool:
    return mime_type == "application/pdf"


def _resolve_doc_path(document: Document) -> str:
    """Resolve the on-disk input path for a document (PDF or staged non-PDF)."""
    if _is_pdf(document.mime_type):
        base = Path(settings.workspace_subdir(str(document.workspace_id), "files"))
    else:
        base = Path(settings.temp_workspace_path(str(document.workspace_id)))
    return str(base / document.stored_filename)


def convert_to_pdf(document_id: str, db_session: Session) -> FileConversionModel:
    query_result = db_session.execute(
        select(Document).where(Document.id == document_id)
    )
    document = query_result.scalar_one_or_none()
    if not document:
        raise ValueError(f"Document with ID {document_id} not found in database.")

    if _is_pdf(document.mime_type):
        raise ValueError(
            f"Document with ID {document_id} is already a PDF, cannot convert."
        )

    input_path = Path(_resolve_doc_path(document)).resolve()
    if not input_path.exists():
        raise ValueError(f"Document file not found on disk: {input_path}")

    output_path = Path(settings.workspace_subdir(str(document.workspace_id), "files"))
    output_path.mkdir(parents=True, exist_ok=True)

    print("-----------------")
    print(f"{settings.workspace_subdir(str(document.workspace_id), 'files')}")

    libreoffice_command = build_libreoffice_command(str(input_path), str(output_path))
    proc = subprocess.run(
        libreoffice_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout = proc.stdout
    stderr = proc.stderr

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
    db_session.commit()
    db_session.refresh(converted_pdf_metadata)

    return converted_pdf_metadata


def convert_to_images(
    document_id: str, db_session: Session
) -> list[FileConversionModel]:
    image_records: list[FileConversionModel] = []
    query_result = db_session.execute(
        select(Document).where(Document.id == document_id)
    )
    document = query_result.scalar_one_or_none()
    if not document:
        raise ValueError(f"Document with ID {document_id} not found in database.")

    file_for_images_path: str | None = None

    if _is_pdf(document.mime_type):
        file_for_images_path = _resolve_doc_path(document)
    else:
        query_file_converted = db_session.execute(
            select(FileConversionModel).where(
                and_(
                    FileConversionModel.file_id == document_id,
                    FileConversionModel.converted_to_extension == "pdf",
                )
            )
        )
        converted_file_metadata = query_file_converted.scalar_one_or_none()
        if converted_file_metadata:
            file_for_images_path = converted_file_metadata.converted_file_path

    if not file_for_images_path:
        raise ValueError(
            f"No PDF file available to work with for Document ID {document_id}. "
            f"Original file is not a PDF and no converted PDF was found."
        )

    if not Path(file_for_images_path).exists():
        raise ValueError(
            f"PDF file path does not exist on disk: {file_for_images_path}"
        )

    images_dir = Path(settings.TEMP_PATH) / str(document.workspace_id)
    images_dir.mkdir(parents=True, exist_ok=True)
    pdf_doc = fitz.open(file_for_images_path)
    try:
        pdf_page_count = pdf_doc.page_count

        for page_num in range(pdf_page_count):
            page = pdf_doc[page_num]
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            image_uuid = uuid.uuid4()
            image_path = images_dir / f"page_{page_num}_{image_uuid}.png"
            img.save(image_path, format="PNG")

            record = FileConversionModel(
                id=image_uuid,
                file_id=document_id,
                converted_file_path=str(image_path),
                converted_mime_type="image/png",
                converted_to_extension="png",
            )
            db_session.add(record)
            image_records.append(record)

        db_session.commit()

        for record in image_records:
            db_session.refresh(record)
    except Exception as e:
        db_session.rollback()
        for record in image_records:
            image_path = Path(str(record.converted_file_path))
            if image_path.exists():
                image_path.unlink()
        raise RuntimeError(
            f"Failed to convert PDF to Images for file {document_id}: {str(e)}"
        ) from e
    finally:
        pdf_doc.close()

    return image_records


def save_ocr_page(
    document_id: str,
    workspace_id: str,
    page_number: int,
    text: str,
    db_session: Session,
) -> FileConversionModel:
    ocr_dir = Path(settings.workspace_subdir(workspace_id, "files"))
    ocr_dir.mkdir(parents=True, exist_ok=True)

    txt_path = ocr_dir / f"{document_id}_OCR_page_{page_number:03d}.txt"

    if not txt_path.exists():
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            raise RuntimeError(
                f"Failed to write OCR text for page {page_number} of "
                f"document {document_id}: {e}"
            ) from e

    existing = db_session.execute(
        select(FileConversionModel).where(
            and_(
                FileConversionModel.file_id == document_id,
                FileConversionModel.converted_to_extension == "txt",
                FileConversionModel.converted_file_path == str(txt_path),
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    record = FileConversionModel(
        file_id=document_id,
        converted_file_path=str(txt_path),
        converted_mime_type="text/plain",
        converted_to_extension="txt",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


logger = logging.getLogger("memory_rag.document_sync")


def ensure_pdf_in_workspace(
    document_id: str, db_session: Session
) -> FileConversionModel | None:
    try:
        query_result = db_session.execute(
            select(Document).where(Document.id == document_id)
        )
        document = query_result.scalar_one_or_none()
        if not document:
            logger.warning("Document %s not found; skipping PDF copy", document_id)
            return None

        workspace_files_dir = Path(
            settings.workspace_subdir(str(document.workspace_id), "files")
        ).resolve()
        workspace_files_dir.mkdir(parents=True, exist_ok=True)

        original_path = Path(_resolve_doc_path(document)).resolve()
        if _is_pdf(document.mime_type):
            source_path = original_path
        else:
            source_path = original_path.with_suffix(".pdf")

        if not source_path.exists():
            logger.warning(
                "PDF source not found for document %s: %s",
                document_id,
                source_path,
            )
            return None

        dest_path = workspace_files_dir / f"{document_id}.pdf"

        if not dest_path.exists():
            try:
                shutil.copy2(source_path, dest_path)
                logger.info("Copied PDF to workspace: %s -> %s", source_path, dest_path)
            except OSError as e:
                logger.error(
                    "Failed to copy PDF to workspace: %s -> %s: %s",
                    source_path,
                    dest_path,
                    e,
                )
                return None

        existing = db_session.execute(
            select(FileConversionModel).where(
                and_(
                    FileConversionModel.file_id == document_id,
                    FileConversionModel.converted_to_extension == "pdf",
                    FileConversionModel.converted_file_path == str(dest_path),
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        record = FileConversionModel(
            file_id=document_id,
            converted_file_path=str(dest_path),
            converted_mime_type="application/pdf",
            converted_to_extension="pdf",
            document_type=DocumentsType.CONVERTED_PDF.value,
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)
        return record
    except Exception as e:
        logger.error("ensure_pdf_in_workspace failed for %s: %s", document_id, e)
        return None


def return_list_images_path(document_id: str, db_session: Session) -> list[str]:
    query_result = db_session.execute(
        select(Document).where(Document.id == document_id)
    )
    document = query_result.scalar_one_or_none()
    if not document:
        raise ValueError(
            f"Document with ID {document_id} not found in database. "
            f"Cannot retrieve image paths for a non-existent file."
        )

    image_paths: list[str] = []
    file_ext = (
        "."
        + (
            document.stored_filename.rsplit(".", 1)[-1]
            if "." in document.stored_filename
            else ""
        ).lower()
    )

    if file_ext in ALLOWED_IMAGE_EXTENSIONS:
        path = _resolve_doc_path(document)
        if not Path(path).exists():
            raise ValueError(
                f"Original image file not found on disk for Document ID {document_id}. "
                f"Expected path: {path}. "
                f"File extension: {file_ext}."
            )
        image_paths.append(path)
    else:
        image_extensions = [ext.lstrip(".") for ext in ALLOWED_IMAGE_EXTENSIONS]
        query_converted = db_session.execute(
            select(FileConversionModel).where(
                and_(
                    FileConversionModel.file_id == document_id,
                    FileConversionModel.converted_to_extension.in_(image_extensions),
                )
            )
        )
        converted_images = query_converted.scalars().all()

        if not converted_images:
            raise ValueError(
                f"No image files available for Document ID {document_id}. "
                f"Original file extension '{file_ext}' is not a valid image "
                f"extension and no converted images were found "
                f"in the database."
            )

        for record in converted_images:
            if not Path(record.converted_file_path).exists():
                raise ValueError(
                    f"Converted image file not found on disk for Document ID {document_id}. "
                    f"Expected path: {record.converted_file_path}. "
                    f"Converted extension: {record.converted_to_extension}. "
                    f"Database record ID: {record.id}"
                )
            image_paths.append(record.converted_file_path)

    if not image_paths:
        raise ValueError(
            f"No image paths were collected for Document ID {document_id}. "
            f"Please check database and file system consistency."
        )

    return image_paths


def translate_convert_markdown(
    document_id: str,
    workspace_id: str,
    db_session: Session,
    finalLangOutpud: LanguageOptions,
):
    """
    This function will
    - Get all the .txt located on the workspace_id
    - one by one extract the content, translate it to the finalLangOutpud language
    - convert the translated content to markdown format using xxxx
    """
