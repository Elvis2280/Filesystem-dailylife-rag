"""Shared, database-backed Ollama model selections for API and workers."""

import logging
import select as select_socket
import threading
from enum import StrEnum

import psycopg2
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.database import (
    Base,
    async_session,
    sync_engine,
    sync_session,
)
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

_ENV_SETTING_FIELDS: dict[ModelRole, str] = {
    ModelRole.OCR: "OLLAMA_MODEL_OCR",
    ModelRole.TRANSLATION: "OLLAMA_MODEL_TRANSLATION",
    ModelRole.EMBEDDING: "OLLAMA_MODEL_EMBEDDING",
    ModelRole.ANSWER: "OLLAMA_MODEL_AGENT",
    ModelRole.FORMATTING: "OLLAMA_MODEL_FORMAT",
    ModelRole.CLEANING: "OLLAMA_MODEL_CLEANER",
}

EDITABLE_ROLES = (
    ModelRole.OCR,
    ModelRole.TRANSLATION,
    ModelRole.ANSWER,
    ModelRole.FORMATTING,
    ModelRole.CLEANING,
)

logger = logging.getLogger("memory_rag.model_preferences")
_NOTIFY_CHANNEL = "ollama_model_preferences_changed"
_cache_lock = threading.RLock()
_listener_lock = threading.Lock()
_listener_stop = threading.Event()
_listener_thread: threading.Thread | None = None
_listener_healthy = False
_cached_model_names: dict[ModelRole, str] | None = None


def default_model_preferences() -> dict[str, str]:
    """Return the environment-configured values used for first seed."""
    return {
        field: environment_model_name(role) for role, field in PREFERENCE_FIELDS.items()
    }


def environment_model_name(role: ModelRole) -> str:
    """Return the task's nonblank environment setting or its code default."""
    setting_field = _ENV_SETTING_FIELDS[role]
    configured_name = getattr(settings, setting_field)
    if isinstance(configured_name, str) and configured_name.strip():
        return configured_name.strip()

    code_default = Settings.model_fields[setting_field].default
    if isinstance(code_default, str) and code_default.strip():
        return code_default.strip()
    raise RuntimeError(f"No default Ollama model is configured for {role.value}")


def effective_model_name(
    role: ModelRole, preferences: OllamaModelPreferences | None
) -> str:
    """Use a saved nonblank selection, otherwise resolve from environment."""
    saved_name = (
        getattr(preferences, PREFERENCE_FIELDS[role], None)
        if preferences is not None
        else None
    )
    if isinstance(saved_name, str) and saved_name.strip():
        return saved_name.strip()
    return environment_model_name(role)


def effective_model_preferences(
    preferences: OllamaModelPreferences | None,
) -> dict[str, str]:
    """Return the effective model name for every role."""
    return {role.value: effective_model_name(role, preferences) for role in ModelRole}


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
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION notify_ollama_model_preferences_changed()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                PERFORM pg_notify('ollama_model_preferences_changed', 'changed');
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        connection.exec_driver_sql("""
            DROP TRIGGER IF EXISTS ollama_model_preferences_changed
            ON ollama_model_preferences
        """)
        connection.exec_driver_sql("""
            CREATE TRIGGER ollama_model_preferences_changed
            AFTER INSERT OR UPDATE OR DELETE ON ollama_model_preferences
            FOR EACH ROW
            EXECUTE FUNCTION notify_ollama_model_preferences_changed()
        """)

    with sync_session.begin() as session:
        session.execute(
            insert(OllamaModelPreferences)
            .values(id=1, **default_model_preferences())
            .on_conflict_do_nothing(index_elements=[OllamaModelPreferences.id])
        )


def required_model_names() -> set[str]:
    """Return all distinct model names currently selected by the server."""
    preferences = get_preferences_sync()
    return set(effective_model_preferences(preferences).values())


def get_preferences_sync(
    session: Session | None = None,
) -> OllamaModelPreferences | None:
    """Read the current selections, optionally using a caller-owned session."""
    if session is not None:
        preferences = session.execute(
            select(OllamaModelPreferences).where(OllamaModelPreferences.id == 1)
        ).scalar_one_or_none()
        return preferences

    with sync_session() as db_session:
        preferences = db_session.execute(
            select(OllamaModelPreferences).where(OllamaModelPreferences.id == 1)
        ).scalar_one_or_none()
        return preferences


async def get_preferences_async() -> OllamaModelPreferences | None:
    """Read preferences from the shared database for async API code."""
    async with async_session() as db_session:
        preferences = await db_session.scalar(
            select(OllamaModelPreferences).where(OllamaModelPreferences.id == 1)
        )
        return preferences


async def save_model_preferences(
    updates: dict[ModelRole, str], session: AsyncSession
) -> OllamaModelPreferences | None:
    """Persist validated role updates together under the singleton row lock."""
    preferences = await session.scalar(
        select(OllamaModelPreferences)
        .where(OllamaModelPreferences.id == 1)
        .with_for_update()
    )
    if preferences is None:
        return None

    for role, model in updates.items():
        setattr(preferences, PREFERENCE_FIELDS[role], model)

    await session.commit()
    return preferences


def get_model_name_sync(role: ModelRole) -> str:
    return get_model_names_sync()[role]


async def get_model_name_async(role: ModelRole) -> str:
    return (await get_model_names_async())[role]


def _model_names_from_row(
    preferences: OllamaModelPreferences | None,
) -> dict[ModelRole, str]:
    return {role: effective_model_name(role, preferences) for role in ModelRole}


def _set_cached_model_names(
    model_names: dict[ModelRole, str], *, listener_refresh: bool = False
) -> None:
    global _cached_model_names
    with _cache_lock:
        if listener_refresh or not _listener_healthy:
            _cached_model_names = dict(model_names)


def _get_cached_model_names() -> dict[ModelRole, str] | None:
    with _cache_lock:
        if _listener_healthy and _cached_model_names is not None:
            return dict(_cached_model_names)
    return None


def get_model_names_sync() -> dict[ModelRole, str]:
    """Return one consistent model snapshot, refreshing from PostgreSQL if needed."""
    cached = _get_cached_model_names()
    if cached is not None:
        return cached
    model_names = _model_names_from_row(get_preferences_sync())
    _set_cached_model_names(model_names)
    return model_names


async def get_model_names_async() -> dict[ModelRole, str]:
    """Return a cached snapshot or asynchronously read it when listening is down."""
    cached = _get_cached_model_names()
    if cached is not None:
        return cached
    model_names = _model_names_from_row(await get_preferences_async())
    _set_cached_model_names(model_names)
    return model_names


def _refresh_model_names_from_database() -> None:
    model_names = _model_names_from_row(get_preferences_sync())
    _set_cached_model_names(model_names, listener_refresh=True)


def _set_listener_health(healthy: bool) -> None:
    global _listener_healthy, _cached_model_names
    with _cache_lock:
        _listener_healthy = healthy
        if not healthy:
            _cached_model_names = None


def _listen_for_model_preference_changes() -> None:
    retry_delay = 1.0
    while not _listener_stop.is_set():
        connection = None
        try:
            connection = psycopg2.connect(
                host=settings.POSTGRES_HOST,
                port=settings.POSTGRES_PORT,
                dbname=settings.POSTGRES_DB,
                user=settings.POSTGRES_USER,
                password=settings.POSTGRES_PASSWORD,
                connect_timeout=5,
            )
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(f"LISTEN {_NOTIFY_CHANNEL}")
            _refresh_model_names_from_database()
            _set_listener_health(True)
            retry_delay = 1.0
            logger.info("Listening for Ollama model preference updates")

            while not _listener_stop.is_set():
                readable, _, _ = select_socket.select([connection], [], [], 1.0)
                if not readable:
                    continue
                connection.poll()
                if connection.notifies:
                    connection.notifies.clear()
                    _refresh_model_names_from_database()
                    logger.info("Refreshed Ollama model preferences from PostgreSQL")
        except Exception:
            if not _listener_stop.is_set():
                logger.exception("Ollama model preference listener disconnected")
        finally:
            _set_listener_health(False)
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    logger.warning("Could not close preference listener connection")

        if not _listener_stop.is_set():
            _listener_stop.wait(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


def start_model_preference_listener() -> None:
    """Start a process-local PostgreSQL notification listener in a daemon thread."""
    global _listener_thread
    with _listener_lock:
        if _listener_thread is not None and _listener_thread.is_alive():
            return
        _listener_stop.clear()
        _listener_thread = threading.Thread(
            target=_listen_for_model_preference_changes,
            name="model-preference-listener",
            daemon=True,
        )
        _listener_thread.start()


def stop_model_preference_listener() -> None:
    """Stop the notification listener and discard the process-local snapshot."""
    global _listener_thread, _cached_model_names
    _listener_stop.set()
    with _listener_lock:
        listener_thread = _listener_thread
    if listener_thread is not None:
        listener_thread.join(timeout=7)
    with _listener_lock, _cache_lock:
        _listener_thread = None
        _cached_model_names = None
