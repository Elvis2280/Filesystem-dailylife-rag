from typing import Any

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    document_id: str = Field(..., description="Generated UUID for the document")
    task_id: str = Field(..., description="Celery task ID for status tracking")
    workspace_id: str = Field(
        ..., description="The workspace ID where the document belongs"
    )
    original_filename: str = Field(
        ..., description="Original name of the uploaded file"
    )
    mime_type: str = Field(..., description="Detected MIME type of the file")
    stored_filename: str = Field(..., description="Filename on disk")
    page_count: int | None = Field(None, description="Number of pages (PDFs only)")
    status: str = Field(..., description="Current processing status")
    message: str = Field(..., description="Human-readable status message")


class FileConversionPayload(BaseModel):
    file_id: str = Field(..., description="UUID of the file to convert")


class FileConversionResponse(BaseModel):
    file_id: str = Field(..., description="UUID of the original file")
    converted_file_path: str = Field(..., description="Path to the converted file")
    converted_mime_type: str = Field(..., description="MIME type of the converted file")
    converted_to_extension: str = Field(
        ..., description="File extension of the converted file"
    )


class DocumentStatusResponse(BaseModel):
    document_id: str = Field(..., description="UUID of the document")
    task_id: str = Field(..., description="Celery task ID for status tracking")
    status: str = Field(
        ...,
        description="Celery task state: PENDING, STARTED, PROGRESS, SUCCESS, FAILURE",
    )
    document_record_status: str = Field(
        ...,
        description="Database document status: in_storage, in_temp_storage, processing_*, completed, failed",
    )
    result: list[dict[str, Any]] | None = Field(
        default=None, description="OCR results if task is SUCCESS"
    )
    error: str | None = Field(default=None, description="Error message if task failed")
    message: str = Field(..., description="Human-readable status message")
