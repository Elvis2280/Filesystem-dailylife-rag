from datetime import datetime
from typing import Union
from uuid import UUID

from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    storage_key: str
    status: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    class Config:
        from_attributes = True


class DisableWorkspaceResponse(BaseModel):
    message: str


class FileNode(BaseModel):
    type: str = "file"
    id: str
    name: str
    original_name: str


class FolderNode(BaseModel):
    type: str = "folder"
    name: str
    path: str
    children: list[Union["FileNode", "FolderNode"]] = []


class WorkspaceTreeNode(BaseModel):
    id: str
    name: str
    status: str
    children: list[FolderNode] = []


class WorkspaceTreeResponse(BaseModel):
    workspaces: list[WorkspaceTreeNode]
