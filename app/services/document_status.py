"""Resolve document state when a worker may have exited without a final event."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_results import failed_task_message
from app.core.constant import FilePipelineStage, FileStatus, REPLACEMENT_UPLOAD_MESSAGE
from app.core.document_lock import document_lock_key
from app.models.document import Document
from app.models.document_event import DocumentEventModel

WORKER_ACTIVITY_GRACE_PERIOD = timedelta(minutes=15)


async def reconcile_replacement_start_failure(
    db: AsyncSession, document: Document, latest_event: DocumentEventModel | None
) -> DocumentEventModel | None:
    """Persist a broker failure if this replacement is still awaiting its worker."""
    if (
        latest_event is None
        or document.status != FileStatus.FILE_UPLOADED.value
        or latest_event.status != FileStatus.FILE_UPLOADED.value
        or latest_event.message != REPLACEMENT_UPLOAD_MESSAGE
        or not document.stored_filename.startswith(
            f"{document.id}_replacement-{latest_event.id}"
        )
    ):
        return None

    error = await failed_task_message(latest_event.id)
    if error is None:
        return None

    current = await db.get(
        Document, document.id, with_for_update=True, populate_existing=True
    )
    if current is None or current.status != FileStatus.FILE_UPLOADED.value:
        return None
    latest_id = await db.scalar(
        select(DocumentEventModel.id)
        .where(DocumentEventModel.document_id == current.id)
        .order_by(DocumentEventModel.created_at.desc(), DocumentEventModel.id.desc())
        .limit(1)
    )
    if latest_id != latest_event.id:
        return None

    stage = FilePipelineStage.OBJECT_STORAGE
    message = f"Replacement worker failed before processing: {error}"[:2000]
    current.status = FileStatus.FAILED.value
    current.last_error = message
    failure = DocumentEventModel(
        document_id=current.id,
        workspace_id=current.workspace_id,
        status=FileStatus.FAILED.value,
        stage=stage.value,
        step=stage.step,
        message=message,
        total_pages=current.page_count,
    )
    db.add(failure)
    await db.flush()
    return failure


async def active_document_worker_ids(
    db: AsyncSession, documents: list[Document]
) -> set[uuid.UUID]:
    """Return document IDs with a worker lock using a single database query."""
    if not documents:
        return set()

    keys_by_document = {
        document.id: document_lock_key(document.id) for document in documents
    }
    active_keys = set(
        (
            await db.scalars(
                text("""
                    WITH requested(lock_key) AS (
                        SELECT unnest(CAST(:lock_keys AS bigint[]))
                    )
                    SELECT DISTINCT requested.lock_key
                    FROM requested
                    WHERE EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_locks
                        WHERE locktype = 'advisory'
                          AND granted
                          AND objsubid = 1
                          AND database = (
                              SELECT oid FROM pg_catalog.pg_database
                              WHERE datname = current_database()
                          )
                          AND classid::bigint =
                              ((requested.lock_key >> 32) & 4294967295)
                          AND objid::bigint =
                              (requested.lock_key & 4294967295)
                    )
                """),
                {"lock_keys": list(keys_by_document.values())},
            )
        ).all()
    )
    return {
        document_id
        for document_id, lock_key in keys_by_document.items()
        if lock_key in active_keys
    }


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
    if document.status == FileStatus.CANCELLING.value:
        return document.status, False
    if document.status in (FileStatus.FAILED.value, FileStatus.COMPLETED.value):
        return document.status, False
    if latest_event is not None and latest_event.status == FileStatus.FAILED.value:
        return FileStatus.FAILED.value, False

    worker_active = await document_worker_is_active(db, document)
    return resolve_document_status_from_activity(document, latest_event, worker_active)


def resolve_document_status_from_activity(
    document: Document,
    latest_event: DocumentEventModel | None,
    worker_active: bool,
) -> tuple[str, bool]:
    """Resolve document status when worker activity has already been checked."""
    if document.status == FileStatus.CANCELLING.value:
        return document.status, False
    if document.status in (FileStatus.FAILED.value, FileStatus.COMPLETED.value):
        return document.status, False
    if latest_event is not None and latest_event.status == FileStatus.FAILED.value:
        return FileStatus.FAILED.value, False

    if worker_active:
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
