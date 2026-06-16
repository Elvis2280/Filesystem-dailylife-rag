from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    """Request schema for workspace creation."""

    name: str = Field(..., min_length=1, max_length=100)


class WorkspaceEntry(BaseModel):
    display_name: str
    slug: str
    workspace_storage_key: str


class WorkspaceResponse(BaseModel):
    id: UUID
    display_name: str
    slug: str
    storage_key: str
    status: str
    created_at: datetime
    updated_at: datetime
    tree: dict[str, list[WorkspaceEntry]] | None = None

    class Config:
        from_attributes = True


class WorkspaceTreeResponse(BaseModel):
    tree: dict[str, list[WorkspaceEntry]]


class DeleteWorkspaceResponse(BaseModel):
    message: str
    tree: dict[str, list[WorkspaceEntry]]
