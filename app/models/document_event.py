from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.workspace import WorkspaceModel


class DocumentEventModel(Base):
    """Append-only processing event used by status history and WebSockets."""

    __tablename__ = "document_events"

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
    document_split_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    translation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    step: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workspace: Mapped[WorkspaceModel] = relationship(
        back_populates="document_events", overlaps="document,events"
    )
    document: Mapped[Document] = relationship(
        back_populates="events", overlaps="workspace"
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "workspace_id"],
            ["documents.id", "documents.workspace_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_split_id", "workspace_id"],
            ["document_splits.id", "document_splits.workspace_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["translation_id", "workspace_id"],
            ["translations.id", "translations.workspace_id"],
            ondelete="CASCADE",
        ),
    )
