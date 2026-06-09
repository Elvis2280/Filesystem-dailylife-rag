"""File upload and persistence service.

Handles the initial file upload flow: saves uploaded files to disk,
creates corresponding database records, and dispatches Celery OCR tasks
for async processing.
"""

from asyncio import subprocess
import shutil
import uuid
from pathlib import Path

from app.models.file_conversions import FileConversionModel
from app.services.ocr.utils import build_libreoffice_command
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.file import FileModel


async def process_file_upload(
    workspace_id: str,
    file: UploadFile,
    db: AsyncSession,
) -> tuple[FileModel, str]:
    """Save file to disk, create DB record, and dispatch Celery OCR task.

    The upload flow is:
    1. Generate a unique file ID and construct a safe filename.
    2. Create the workspace upload directory if it doesn't exist.
    3. Stream the uploaded file to disk using shutil.copyfileobj.
    4. Create a FileModel record in Postgres with metadata and status.
    5. Dispatch a Celery task for async OCR processing.

    Args:
        workspace_id: Validated workspace UUID string.
        file: FastAPI UploadFile object containing the uploaded content.
        db: Async SQLAlchemy session for database operations.

    Returns:
        Tuple of (FileModel database record, Celery task ID for tracking).
    """
    file_id = uuid.uuid4()
    # Extract file extension safely; fallback to empty string if no dot
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else ""
    filename = f"{file_id}.{ext}"

    # Ensure workspace upload directory exists
    upload_dir = Path(settings.UPLOAD_PATH) / workspace_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename

    # Stream file to disk (avoids loading entire file into memory)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = file_path.stat().st_size

    # Create database record with initial state
    db_file = FileModel(
        id=file_id,
        workspace_id=uuid.UUID(workspace_id),
        original_filename=file.filename,
        storage_path=str(file_path),
        file_size=file_size,
        mime_type=file.content_type or "application/octet-stream",
        file_extension=ext,
        status="in_storage",
    )
    db.add(db_file)
    await db.commit()
    await db.refresh(db_file)

    return db_file


async def save_converted_file_metadata(
    file_id: str,
    db_session: AsyncSession,
) -> FileConversionModel:
    """Save metadata for a converted file (e.g., PDF generated from Office doc).

    This is used to track the new file created by LibreOffice conversion,
    which will then be processed by the OCR pipeline.

    Args:
        file_id: ID of the original uploaded file that was converted.
        db_session: Async SQLAlchemy session for database operations.
    Returns:
        The created FileConversionModel instance with metadata about the converted file.
    """
    converted_result = await convert_to_pdf(file_id, db_session)
    converted_metadata = FileConversionModel(
        file_id=converted_result.file_id,
        converted_file_path=converted_result.converted_file_path,
        converted_mime_type=converted_result.converted_mime_type,
        converted_to_extension=converted_result.converted_to_extension,
    )
    db_session.add(converted_metadata)
    await db_session.commit()
    await db_session.refresh(converted_metadata)

    return converted_metadata


async def convert_to_pdf(file_id: str, db_session: AsyncSession) -> FileConversionModel:
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

    query_result = await db_session.execute(
        select(FileModel).where(FileModel.id == file_id)
    )
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
    libreoffice_command = build_libreoffice_command(input_path, output_path)
    proc = await subprocess.create_subprocess_exec(
        *libreoffice_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

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

    return converted_pdf_metadata
