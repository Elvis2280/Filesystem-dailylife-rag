import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DisabledWorkspace(Base):
    """Audit record for disabled workspaces.

    Preserves a record of disabled workspaces including the language
    directory that was affected, enabling potential re-enablement.
    """

    __tablename__ = "disabled_workspace"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_storage_key: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )
    lang: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
