import uuid

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class FileModel(Base):
    __tablename__ = "files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    original_filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_extension = Column(String(20), nullable=False)
    mime_type = Column(String(100), nullable=False)
    status = Column(String(50), default="in_storage")
    extracted_text = Column(Text, nullable=True)
    detected_language = Column(String(10), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
