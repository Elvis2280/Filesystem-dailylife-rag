from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.document_event import DocumentEventModel
    from app.models.document_split import DocumentSplitModel
    from app.models.workspace import WorkspaceModel


class Document(Base):
    """One physical file belonging to a workspace."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    file_role: Mapped[str] = mapped_column(
        String(30), nullable=False, default="original", server_default="original"
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_area: Mapped[str] = mapped_column(
        String(20), nullable=False, default="workspace", server_default="workspace"
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_extension: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="file_uploaded",
        server_default="file_uploaded",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    workspace: Mapped[WorkspaceModel] = relationship(back_populates="documents")
    parent: Mapped[Document | None] = relationship(
        remote_side="Document.id", back_populates="children", overlaps="workspace"
    )
    children: Mapped[list[Document]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        overlaps="workspace",
    )
    splits: Mapped[list[DocumentSplitModel]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list[DocumentEventModel]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("size >= 0", name="ck_documents_size_nonnegative"),
        CheckConstraint("attempt_count >= 0", name="ck_documents_attempt_nonnegative"),
        CheckConstraint(
            "file_role IN ('original', 'converted_pdf')",
            name="ck_documents_file_role",
        ),
        CheckConstraint(
            "storage_area IN ('workspace', 'temp')", name="ck_documents_storage_area"
        ),
        UniqueConstraint("id", "workspace_id", name="uq_documents_id_workspace"),
        ForeignKeyConstraint(
            ["parent_document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "parent_document_id", "file_role", name="uq_documents_parent_role"
        ),
        Index(
            "uq_documents_workspace_original_checksum",
            "workspace_id",
            "checksum_sha256",
            unique=True,
            postgresql_where=text(
                "file_role = 'original' AND checksum_sha256 IS NOT NULL"
            ),
        ),
        Index("ix_documents_workspace_status", "workspace_id", "status"),
    )
