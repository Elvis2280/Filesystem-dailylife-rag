"""Shared, database-backed Ollama model selections for API and workers."""

from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base, async_session, sync_engine, sync_session
from app.models.ollama_model_preferences import OllamaModelPreferences


class ModelRole(StrEnum):
    OCR = "ocr"
    TRANSLATION = "translation"
    EMBEDDING = "embedding"
    ANSWER = "answer"
    FORMATTING = "formatting"
    CLEANING = "cleaning"


PREFERENCE_FIELDS: dict[ModelRole, str] = {
    ModelRole.OCR: "ocr_model",
    ModelRole.TRANSLATION: "translation_model",
    ModelRole.EMBEDDING: "embedding_model",
    ModelRole.ANSWER: "answer_model",
    ModelRole.FORMATTING: "formatting_model",
    ModelRole.CLEANING: "cleaning_model",
}

EDITABLE_ROLES = (
    ModelRole.OCR,
    ModelRole.TRANSLATION,
    ModelRole.ANSWER,
)


def default_model_preferences() -> dict[str, str]:
    """Return the legacy environment-configured values used for first seed."""
    return {
        "ocr_model": settings.OLLAMA_MODEL_OCR,
        "translation_model": settings.OLLAMA_MODEL_TRANSLATION,
        "embedding_model": settings.OLLAMA_MODEL_EMBEDDING,
        "answer_model": settings.OLLAMA_MODEL_AGENT,
        "formatting_model": settings.OLLAMA_MODEL_FORMAT,
        "cleaning_model": settings.OLLAMA_MODEL_CLEANER,
    }


def ensure_model_preferences_storage() -> None:
    """Create the preferences table and seed its singleton row exactly once."""
    with sync_engine.begin() as connection:
        # Initialize this small settings table before API and worker processes
        # begin reading shared preferences.
        connection.exec_driver_sql(
            "SELECT pg_advisory_xact_lock(hashtext('ollama_model_preferences'))"
        )
        Base.metadata.create_all(
            bind=connection,
            tables=[OllamaModelPreferences.__table__],
        )

    with sync_session.begin() as session:
        session.execute(
            insert(OllamaModelPreferences)
            .values(id=1, **default_model_preferences())
            .on_conflict_do_nothing(index_elements=[OllamaModelPreferences.id])
        )


def required_model_names() -> set[str]:
    """Return all distinct model names currently selected by the server."""
    preferences = get_preferences_sync()
    return {str(getattr(preferences, field)) for field in PREFERENCE_FIELDS.values()}


def get_preferences_sync(session: Session | None = None) -> OllamaModelPreferences:
    """Read the current selections, optionally using a caller-owned session."""
    if session is not None:
        preferences = session.execute(
            select(OllamaModelPreferences).where(OllamaModelPreferences.id == 1)
        ).scalar_one_or_none()
        if preferences is None:
            raise RuntimeError("Ollama model preferences have not been initialized")
        return preferences

    with sync_session() as db_session:
        preferences = db_session.execute(
            select(OllamaModelPreferences).where(OllamaModelPreferences.id == 1)
        ).scalar_one_or_none()
        if preferences is None:
            raise RuntimeError("Ollama model preferences have not been initialized")
        return preferences


async def get_preferences_async() -> OllamaModelPreferences:
    """Read preferences from the shared database for async API code."""
    async with async_session() as db_session:
        preferences = await db_session.scalar(
            select(OllamaModelPreferences).where(OllamaModelPreferences.id == 1)
        )
        if preferences is None:
            raise RuntimeError("Ollama model preferences have not been initialized")
        return preferences


def get_model_name_sync(role: ModelRole) -> str:
    preferences = get_preferences_sync()
    return str(getattr(preferences, PREFERENCE_FIELDS[role]))


async def get_model_name_async(role: ModelRole) -> str:
    preferences = await get_preferences_async()
    return str(getattr(preferences, PREFERENCE_FIELDS[role]))
