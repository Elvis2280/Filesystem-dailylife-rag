"""Resolve document state when a worker may have exited without a final event."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constant import FileStatus
from app.core.document_lock import document_lock_key
from app.models.document import Document
from app.models.document_event import DocumentEventModel

WORKER_ACTIVITY_GRACE_PERIOD = timedelta(minutes=15)


async def document_worker_is_active(db: AsyncSession, document: Document) -> bool:
    # PostgreSQL exposes the two halves of a bigint advisory key as unsigned OIDs.
    key = document_lock_key(document.id)
    return bool(
        await db.scalar(
            text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_catalog.pg_locks
            WHERE locktype = 'advisory' AND granted AND objsubid = 1
            AND database = (SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database())
            AND classid::bigint = :high AND objid::bigint = :low
        )
    """),
            {"high": (key >> 32) & 0xFFFFFFFF, "low": key & 0xFFFFFFFF},
        )
    )


def document_has_recent_activity(
    document: Document,
    latest_event: DocumentEventModel | None,
) -> bool:
    last_activity = (
        latest_event.created_at
        if latest_event is not None
        else document.updated_at or document.created_at
    )
    return (
        last_activity is not None
        and datetime.now(timezone.utc) - last_activity < WORKER_ACTIVITY_GRACE_PERIOD
    )


async def resolve_document_status(
    db: AsyncSession,
    document: Document,
    latest_event: DocumentEventModel | None,
) -> tuple[str, bool]:
    """Return the effective state and whether a worker disappeared mid-job."""
    if document.status in (FileStatus.FAILED.value, FileStatus.COMPLETED.value):
        return document.status, False
    if latest_event is not None and latest_event.status == FileStatus.FAILED.value:
        return FileStatus.FAILED.value, False

    if await document_worker_is_active(db, document):
        return document.status, False

    if document_has_recent_activity(document, latest_event):
        return document.status, False

    return FileStatus.FAILED.value, True


def document_failure_message(
    document: Document,
    latest_event: DocumentEventModel | None,
    worker_stopped: bool,
) -> str:
    if document.last_error:
        return document.last_error
    if (
        latest_event
        and latest_event.status == FileStatus.FAILED.value
        and latest_event.message
    ):
        return latest_event.message
    if worker_stopped:
        return "Worker stopped before processing completed. Retry is available."
    return "Document processing failed"
