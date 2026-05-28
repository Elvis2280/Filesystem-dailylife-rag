import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.workspace import WorkspaceModel
from app.schemas.file import FileUploadResponse
from app.services.storage.file import process_file_upload

router = APIRouter(prefix="/api/v1", tags=["files"])

ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
    "image/png",
    "image/jpeg",
}


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


@router.post(
    "/files/upload",
    response_model=FileUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_file(
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not _is_valid_uuid(workspace_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace_id must be a valid UUID",
        )

    result = await db.execute(
        select(WorkspaceModel).filter_by(storage_key=workspace_id)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found",
        )

    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File type '{file.content_type}' not allowed. "
                "Supported types: PDF, PNG, JPG, JPEG"
            ),
        )

    file_record, task_id = await process_file_upload(str(workspace.id), file, db)

    return FileUploadResponse(
        file_id=str(file_record.id),
        task_id=task_id,
        workspace_id=workspace_id,
        original_filename=file_record.original_filename,
        mime_type=file_record.mime_type,
        status=file_record.status,
        message="File uploaded and queued for OCR processing.",
    )
