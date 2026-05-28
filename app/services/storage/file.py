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

    Args:
        workspace_id: Validated workspace UUID string.
        file: FastAPI UploadFile object.
        db: Async SQLAlchemy session.

    Returns:
        Tuple of (FileModel database record, Celery task ID).
    """
    file_id = uuid.uuid4()
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else ""
    filename = f"{file_id}.{ext}"

    upload_dir = Path(settings.UPLOAD_PATH) / workspace_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = file_path.stat().st_size

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

    task = celery_app.send_task(
        "workers.ocr.tasks.process_file",
        args=[
            str(file_id),
            str(file_path),
            file.content_type or "application/octet-stream",
        ],
    )

    return db_file, task.id
