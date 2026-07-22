import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FileConversionModel(Base):
    """SQLAlchemy model for file conversion records.

    Tracks format conversions such as document-to-PDF and PDF-to-image,
    including the output path, target MIME type, and document type tag.
    """

    __tablename__ = "file_conversions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False
    )
    converted_file_path: Mapped[str] = mapped_column(String, nullable=False)
    converted_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    converted_to_extension: Mapped[str] = mapped_column(String(20), nullable=False)
    document_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
