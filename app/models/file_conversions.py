import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class FileConversionModel(Base):
    __tablename__ = "file_conversions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("files.id"), nullable=False)
    converted_file_path = Column(String, nullable=False)
    converted_mime_type = Column(String(100), nullable=False)
    converted_to_extension = Column(String(20), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
