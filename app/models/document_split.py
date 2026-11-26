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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.translation import TranslationModel
    from app.models.workspace import WorkspaceModel


class DocumentSplitModel(Base):
    """One page image and its page-level OCR/formatting outputs."""

    __tablename__ = "document_splits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="image_ready", server_default="image_ready"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    ocr_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ocr_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    markdown_storage_key: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    markdown_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
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

    workspace: Mapped[WorkspaceModel] = relationship(
        back_populates="document_splits", overlaps="document,splits"
    )
    document: Mapped[Document] = relationship(
        back_populates="splits", overlaps="workspace"
    )
    translations: Mapped[list[TranslationModel]] = relationship(
        back_populates="document_split",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("page_number >= 1", name="ck_document_splits_page_positive"),
        CheckConstraint("size >= 0", name="ck_document_splits_size_nonnegative"),
        CheckConstraint(
            "attempt_count >= 0", name="ck_document_splits_attempt_nonnegative"
        ),
        CheckConstraint(
            "ocr_size IS NULL OR ocr_size >= 0",
            name="ck_document_splits_ocr_size_nonnegative",
        ),
        CheckConstraint(
            "markdown_size IS NULL OR markdown_size >= 0",
            name="ck_document_splits_markdown_size_nonnegative",
        ),
        UniqueConstraint("document_id", "page_number", name="uq_document_split_page"),
        UniqueConstraint("document_id", "storage_key", name="uq_document_split_path"),
        UniqueConstraint("id", "workspace_id", name="uq_document_splits_id_workspace"),
        ForeignKeyConstraint(
            ["document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            ondelete="CASCADE",
        ),
        Index("ix_document_splits_workspace_status", "workspace_id", "status"),
    )
