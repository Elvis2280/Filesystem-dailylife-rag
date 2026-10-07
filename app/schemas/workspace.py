from datetime import datetime
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


class WorkspaceArtifactFile(BaseModel):
    id: str
    name: str
    file_role: str
    path: str
    status: str
    mime_type: str
    created_at: datetime | None = None


class WorkspaceTranslationFile(BaseModel):
    id: str
    name: str
    language: str
    page_number: int
    path: str
    status: str
    mime_type: str
    created_at: datetime | None = None


class WorkspaceTranslations(BaseModel):
    japanese: list[WorkspaceTranslationFile] = Field(default_factory=list)
    english: list[WorkspaceTranslationFile] = Field(default_factory=list)


class WorkspacePageImage(BaseModel):
    id: str
    name: str
    document_id: str
    page_number: int
    path: str
    status: str
    mime_type: str


class WorkspaceFileNode(BaseModel):
    id: str
    name: str
    status: str
    language: str | None = None
    mime_type: str
    page_count: int | None = None
    created_at: datetime | None = None
    original_files: list[WorkspaceArtifactFile] = Field(default_factory=list)
    translations: WorkspaceTranslations = Field(default_factory=WorkspaceTranslations)
    pages: list[WorkspacePageImage] = Field(default_factory=list)


class WorkspaceTreeNode(BaseModel):
    id: str
    name: str
    status: str
    files: list[WorkspaceFileNode] = Field(default_factory=list)


class WorkspaceTreeResponse(BaseModel):
    workspaces: list[WorkspaceTreeNode]
