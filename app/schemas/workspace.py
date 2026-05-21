from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class WorkspaceResponse(BaseModel):
    id: UUID
    display_name: str
    slug: str
    storage_key: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
