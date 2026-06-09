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
    file_extension: str = Field(..., description="File extension of the uploaded file")
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
