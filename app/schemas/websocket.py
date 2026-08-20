from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WebSocketProgressMessage(BaseModel):
    """Schema for WebSocket progress messages during file processing.

    Sent over Redis pubsub and relayed to WebSocket clients for
    real-time status updates across the pipeline stages.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: str = Field(
        ..., description="FileStatus value: file_uploaded, file_conversion_started, ..."
    )
    step: int | None = Field(default=None, description="Current numeric pipeline step")
    step_total: int | None = Field(
        default=None,
        alias="stepTotal",
        description="Total number of pipeline steps",
    )
    stage: str = Field(..., description="Stage name matching FilePipelineStage value")
    message: str = Field(..., description="Human-readable status message")
    document_id: str = Field(..., description="Document UUID")
    page_number: int | None = Field(
        default=None, description="1-indexed current page (OCR stage)"
    )
    total_pages: int | None = Field(default=None, description="Total pages to process")
    result: list[dict[str, Any]] | None = Field(
        default=None, description="OCR results on SUCCESS"
    )
    error: str | None = Field(default=None, description="Error message on FAILURE")
    timestamp: str = Field(..., description="ISO timestamp")
