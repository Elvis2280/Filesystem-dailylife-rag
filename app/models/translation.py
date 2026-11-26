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
    from app.models.document_split import DocumentSplitModel
    from app.models.workspace import WorkspaceModel


class TranslationModel(Base):
    """A translated file produced for one processed document page."""

    __tablename__ = "translations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_split_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="completed", server_default="completed"
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

    workspace: Mapped[WorkspaceModel] = relationship(
        back_populates="translations", overlaps="document_split,translations"
    )
    document_split: Mapped[DocumentSplitModel] = relationship(
        back_populates="translations", overlaps="workspace"
    )

    __table_args__ = (
        CheckConstraint("size >= 0", name="ck_translations_size_nonnegative"),
        CheckConstraint(
            "attempt_count >= 0", name="ck_translations_attempt_nonnegative"
        ),
        UniqueConstraint(
            "document_split_id", "language", name="uq_translations_split_language"
        ),
        UniqueConstraint("id", "workspace_id", name="uq_translations_id_workspace"),
        ForeignKeyConstraint(
            ["document_split_id", "workspace_id"],
            ["document_splits.id", "document_splits.workspace_id"],
            ondelete="CASCADE",
        ),
        Index("ix_translations_workspace_status", "workspace_id", "status"),
    )
