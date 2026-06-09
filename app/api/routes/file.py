import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.constant import ALLOWED_DOCUMENT_MIME_TYPES
from app.models.workspace import WorkspaceModel
from app.schemas.file import (
    FileUploadResponse,
    FileConversionPayload,
    FileConversionResponse,
)
from app.services.storage.file import process_file_upload, save_converted_file_metadata

router = APIRouter(prefix="/api/v1", tags=["files"])


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
    # TODO: Move this validation to validators.py
    if not _is_valid_uuid(workspace_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace_id must be a valid UUID",
        )

    if file.content_type not in ALLOWED_DOCUMENT_MIME_TYPES:
        allowed = ", ".join(sorted(ALLOWED_DOCUMENT_MIME_TYPES))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{file.content_type}' not allowed. Supported types: {allowed}",
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

    try:
        file_record = await process_file_upload(str(workspace.id), file, db)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {e}",
        )

    # TODO: If the conversion fails, we should update the file record status to 'conversion_failed' and include error details for better observability and debugging.
    # try:
    #     converted_to_pdf = await save_converted_file_metadata(file_record, db)
    # except ValueError as e:
    #     raise HTTPException(
    #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         detail=str(e),
    #     )
    # except Exception as e:
    #     raise HTTPException(
    #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #         detail=f"Failed to save converted file metadata: {e}",
    #     )

    return FileUploadResponse(
        file_id=str(file_record.id),
        task_id="1",  # TODO: Return actual task ID from Celery when implemented
        workspace_id=workspace_id,
        file_extension=file_record.file_extension,
        original_filename=file_record.original_filename,
        mime_type=file_record.mime_type,
        status=file_record.status,
        message="File uploaded and queued for OCR processing.",
    )


@router.post(
    "/files/convert",
    response_model=FileConversionResponse,
    status_code=status.HTTP_200_OK,
)
async def convert_file(
    payload: FileConversionPayload,
    db: AsyncSession = Depends(get_db),
):
    file_id = payload.file_id
    if not _is_valid_uuid(file_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_id must be a valid UUID",
        )

    try:
        converted_metadata = await save_converted_file_metadata(file_id, db)
        return FileConversionResponse(
            file_id=file_id,
            converted_file_path=converted_metadata.converted_file_path,
            converted_mime_type=converted_metadata.converted_mime_type,
            converted_to_extension=converted_metadata.converted_to_extension,
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
