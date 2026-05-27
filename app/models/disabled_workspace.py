import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class DisabledWorkspace(Base):
    __tablename__ = "disabled_workspace"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_storage_key = Column(String, nullable=False, index=True)
    lang = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
