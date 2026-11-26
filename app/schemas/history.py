from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentHistoryEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    stage: str | None
    step: str | None
    message: str | None
    page_number: int | None
    total_pages: int | None
    created_at: datetime


class DocumentHistoryResponse(BaseModel):
    document_id: UUID
    events: list[DocumentHistoryEvent]
    next_cursor: UUID | None


class HistoryDocumentItem(BaseModel):
    document_id: UUID
    original_filename: str
    workspace_id: UUID
    workspace_name: str
    created_at: datetime
    status: str
    stage: str | None = None
    step: str | None = None
    message: str
    page_number: int | None = None
    total_pages: int | None = None
    error: str | None = None


class DocumentHistoryListResponse(BaseModel):
    items: list[HistoryDocumentItem]
    next_cursor: UUID | None


HistorySort = Literal["oldest", "newest"]
HistoryStatus = Literal["active", "complete"]
