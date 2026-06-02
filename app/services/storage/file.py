"""File upload and persistence service.

Handles the initial file upload flow: saves uploaded files to disk,
creates corresponding database records, and dispatches Celery OCR tasks
for async processing.
"""

import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.file import FileModel
from workers.celery_app import celery_app


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
        status="in_storage",
    )
    db.add(db_file)
    await db.commit()
    await db.refresh(db_file)

    # Dispatch async OCR task to Celery worker
    task = celery_app.send_task(
        "workers.ocr.tasks.process_file",
        args=[
            str(file_id),
            str(file_path),
            file.content_type or "application/octet-stream",
        ],
    )

    return db_file, task.id
