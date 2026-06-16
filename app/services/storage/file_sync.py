import subprocess
import uuid
from pathlib import Path

import fitz
from PIL import Image
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.constant import ALLOWED_IMAGE_EXTENSIONS
from app.models.file import FileModel
from app.models.file_conversions import FileConversionModel
from app.services.ocr.utils import build_libreoffice_command


def convert_to_pdf(file_id: str, db_session: Session) -> FileConversionModel:
    """Convert an Office document (.docx, .pptx, etc.) to PDF using LibreOffice.

    Uses LibreOffice in headless mode to convert non-PDF files to PDF format.
    The generated PDF is written to the same directory as the input file.

    Args:
        file_id: UUID of the file to convert.
        db_session: Async SQLAlchemy session for database lookups.

    Returns:
        FileConversionModel containing the path to the generated PDF.

    Raises:
        ValueError: If the file is not found in the database, is already a PDF,
            or does not exist on disk.
        RuntimeError: If LibreOffice conversion fails or the output PDF is not created.
    """

    query_result = db_session.execute(select(FileModel).where(FileModel.id == file_id))
    file_metadata = query_result.scalar_one_or_none()
    if not file_metadata:
        raise ValueError(f"File with ID {file_id} not found in database.")
    file_path = file_metadata.storage_path

    if file_metadata.file_extension == "pdf":
        raise ValueError(f"File with ID {file_id} is already a PDF, cannot convert.")

    if not file_path or not Path(file_path).exists():
        raise ValueError(f"File path for ID {file_id} does not exist on disk.")

    # For non-PDF files, attempt to open with LibreOffice to convert to PDF first
    input_path = Path(file_path).resolve()
    output_path = input_path.parent
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

    expected_pdf = input_path.with_suffix(".pdf")
    if not expected_pdf.exists():
        raise RuntimeError(
            f"Expected converted PDF not found at {expected_pdf} after LibreOffice conversion. "
            f"stderr: {stderr.decode().strip()}, stdout: {stdout.decode().strip()}"
        )

    converted_pdf_metadata = FileConversionModel(
        file_id=file_id,
        converted_file_path=str(expected_pdf),
        converted_mime_type="application/pdf",
        converted_to_extension="pdf",
    )

    db_session.add(converted_pdf_metadata)
    db_session.commit()
    db_session.refresh(converted_pdf_metadata)

    return converted_pdf_metadata


def convert_to_images(file_id: str, db_session: Session) -> list[FileConversionModel]:
    image_records: list[FileConversionModel] = []
    query_result = db_session.execute(select(FileModel).where(FileModel.id == file_id))
    # TODO: Move the validation of file_id to a helper function so it doesn't repeat the same code per service
    file_metadata = query_result.scalar_one_or_none()
    if not file_metadata:
        raise ValueError(f"File with ID {file_id} not found in database.")

    file_for_images_path: str | None = None

    if file_metadata.file_extension == "pdf":
        file_for_images_path = file_metadata.storage_path
    else:
        query_file_converted = db_session.execute(
            select(FileConversionModel).where(
                and_(
                    FileConversionModel.file_id == file_id,
                    FileConversionModel.converted_to_extension == "pdf",
                )
            )
        )
        converted_file_metadata = query_file_converted.scalar_one_or_none()
        if converted_file_metadata:
            file_for_images_path = converted_file_metadata.converted_file_path

    if not file_for_images_path:
        raise ValueError(
            f"No PDF file available to work with for File ID {file_id}. "
            f"Original file is not a PDF and no converted PDF was found."
        )

    if not Path(file_for_images_path).exists():
        raise ValueError(
            f"PDF file path does not exist on disk: {file_for_images_path}"
        )

    pdf_dir = Path(file_for_images_path).parent
    images_dir = pdf_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    pdf_doc = fitz.open(file_for_images_path)
    try:
        pdf_page_count = pdf_doc.page_count

        for page_num in range(pdf_page_count):
            page = pdf_doc[page_num]
            # Move dpi value to a setting value
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            image_uuid = uuid.uuid4()
            image_path = images_dir / f"page_{page_num}_{image_uuid}.png"
            # TODO: Move the document type to use a setting value
            img.save(image_path, format="PNG")

            record = FileConversionModel(
                id=image_uuid,
                file_id=file_id,
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
            f"Failed to convert PDF to Images for file {file_id}: {str(e)}"
        ) from e
    finally:
        pdf_doc.close()

    return image_records


def return_list_images_path(file_id: str, db_session: Session) -> list[str]:
    query_result = db_session.execute(select(FileModel).where(FileModel.id == file_id))
    file_metadata = query_result.scalar_one_or_none()
    if not file_metadata:
        raise ValueError(
            f"File with ID {file_id} not found in database. "
            f"Cannot retrieve image paths for a non-existent file."
        )

    image_paths: list[str] = []
    file_ext = f".{file_metadata.file_extension.lstrip('.')}"

    if file_ext in ALLOWED_IMAGE_EXTENSIONS:
        if not Path(file_metadata.storage_path).exists():
            raise ValueError(
                f"Original image file not found on disk for File ID {file_id}. "
                f"Expected path: {file_metadata.storage_path}. "
                f"File extension: {file_ext}."
            )
        image_paths.append(file_metadata.storage_path)
    else:
        image_extensions = [ext.lstrip(".") for ext in ALLOWED_IMAGE_EXTENSIONS]
        query_converted = db_session.execute(
            select(FileConversionModel).where(
                and_(
                    FileConversionModel.file_id == file_id,
                    FileConversionModel.converted_to_extension.in_(image_extensions),
                )
            )
        )
        converted_images = query_converted.scalars().all()

        if not converted_images:
            raise ValueError(
                f"No image files available for File ID {file_id}. "
                f"Original file extension '{file_ext}' is not a valid image "
                f"extension and no converted images were found "
                f"in the database."
            )

        for record in converted_images:
            if not Path(record.converted_file_path).exists():
                raise ValueError(
                    f"Converted image file not found on disk for File ID {file_id}. "
                    f"Expected path: {record.converted_file_path}. "
                    f"Converted extension: {record.converted_to_extension}. "
                    f"Database record ID: {record.id}"
                )
            image_paths.append(record.converted_file_path)

    if not image_paths:
        raise ValueError(
            f"No image paths were collected for File ID {file_id}. "
            f"Please check database and file system consistency."
        )

    return image_paths
