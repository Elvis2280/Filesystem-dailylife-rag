from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_event import DocumentEventModel
    from app.models.document_split import DocumentSplitModel
    from app.models.translation import TranslationModel


class WorkspaceModel(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    documents: Mapped[list[Document]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
        overlaps="parent,children",
    )
    translations: Mapped[list[TranslationModel]] = relationship(
        back_populates="workspace",
        passive_deletes=True,
        overlaps="document_split,translations",
    )
    document_splits: Mapped[list[DocumentSplitModel]] = relationship(
        back_populates="workspace",
        passive_deletes=True,
        overlaps="document,splits",
    )
    document_events: Mapped[list[DocumentEventModel]] = relationship(
        back_populates="workspace",
        passive_deletes=True,
        overlaps="document,events",
    )
