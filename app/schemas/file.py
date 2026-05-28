from pydantic import BaseModel, Field


class FileUploadResponse(BaseModel):
    file_id: str = Field(..., description="Generated UUID for the file")
    task_id: str = Field(..., description="Celery task ID for status tracking")
    workspace_id: str = Field(
        ..., description="The workspace ID where the file belongs"
    )
    original_filename: str = Field(
        ..., description="Original name of the uploaded file"
    )
    mime_type: str = Field(..., description="Detected MIME type of the file")
    status: str = Field(..., description="Current processing status")
    message: str = Field(..., description="Human-readable status message")
