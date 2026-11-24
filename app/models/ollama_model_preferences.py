from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OllamaModelPreferences(Base):
    """The single server-wide set of Ollama model selections."""

    __tablename__ = "ollama_model_preferences"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_ollama_model_preferences_singleton"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    ocr_model: Mapped[str] = mapped_column(String(255), nullable=False)
    translation_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_model: Mapped[str] = mapped_column(String(255), nullable=False)
    formatting_model: Mapped[str] = mapped_column(String(255), nullable=False)
    cleaning_model: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
