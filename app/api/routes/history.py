"""Document history and upload listing endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constant import FileStatus
from app.core.database import get_db
from app.models.document import Document
from app.models.document_event import DocumentEventModel
from app.models.workspace import WorkspaceModel
from app.schemas.history import (
    DocumentHistoryEvent,
    DocumentHistoryListResponse,
    DocumentHistoryResponse,
    HistoryDocumentItem,
    HistorySort,
    HistoryStatus,
)
from app.services.document_status import (
    active_document_worker_ids,
    document_failure_message,
    reconcile_replacement_start_failure,
    resolve_document_status_from_activity,
)

router = APIRouter(prefix="/api/v1", tags=["history"])


async def _latest_events_by_document(
    db: AsyncSession, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DocumentEventModel]:
    if not document_ids:
        return {}

    ranked_events = (
        select(
            DocumentEventModel.id.label("event_id"),
            DocumentEventModel.document_id.label("document_id"),
            func.row_number()
            .over(
                partition_by=DocumentEventModel.document_id,
                order_by=(
                    DocumentEventModel.created_at.desc(),
                    DocumentEventModel.id.desc(),
                ),
            )
            .label("event_rank"),
        )
        .where(DocumentEventModel.document_id.in_(document_ids))
        .subquery()
    )
    events = await db.scalars(
        select(DocumentEventModel)
        .join(ranked_events, ranked_events.c.event_id == DocumentEventModel.id)
        .where(ranked_events.c.event_rank == 1)
    )
    return {event.document_id: event for event in events}


@router.get("/history", response_model=DocumentHistoryListResponse)
async def list_document_history(
    sort: HistorySort = Query(default="oldest"),
    workspace: uuid.UUID | None = Query(default=None),
    status_filter: Annotated[HistoryStatus, Query(alias="status")] = "active",
    limit: int = Query(default=50, ge=1, le=200),
    cursor: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> DocumentHistoryListResponse:
    """List uploaded documents filtered by workspace and processing state."""
    cursor_document = None
    if cursor is not None:
        cursor_query = select(Document).where(
            Document.id == cursor,
            Document.parent_document_id.is_(None),
            Document.file_role == "original",
        )
        if workspace is not None:
            cursor_query = cursor_query.where(Document.workspace_id == workspace)
        cursor_document = await db.scalar(cursor_query)
        if cursor_document is None:
            raise HTTPException(status_code=400, detail="Invalid history cursor")

    query = (
        select(Document, WorkspaceModel.name)
        .join(WorkspaceModel, WorkspaceModel.id == Document.workspace_id)
        .where(
            Document.parent_document_id.is_(None),
            Document.file_role == "original",
        )
    )
    if workspace is not None:
        query = query.where(Document.workspace_id == workspace)
    if status_filter == "complete":
        query = query.where(Document.status == FileStatus.COMPLETED.value)
    else:
        query = query.where(Document.status != FileStatus.COMPLETED.value)

    if cursor_document is not None:
        cursor_order = (cursor_document.created_at, cursor_document.id)
        if sort == "oldest":
            query = query.where(tuple_(Document.created_at, Document.id) > cursor_order)
        else:
            query = query.where(tuple_(Document.created_at, Document.id) < cursor_order)

    ordering = (
        (Document.created_at.asc(), Document.id.asc())
        if sort == "oldest"
        else (Document.created_at.desc(), Document.id.desc())
    )
    result = await db.execute(query.order_by(*ordering).limit(limit + 1))
    rows = result.all()
    page_rows = rows[:limit]
    documents = [document for document, _ in page_rows]
    latest_events = await _latest_events_by_document(
        db, [document.id for document in documents]
    )

    needs_worker_check = [
        document
        for document in documents
        if document.status not in (FileStatus.FAILED.value, FileStatus.COMPLETED.value)
        and (
            latest_events.get(document.id) is None
            or latest_events[document.id].status != FileStatus.FAILED.value
        )
    ]
    active_workers = await active_document_worker_ids(db, needs_worker_check)

    items = []
    for document, workspace_name in page_rows:
        latest_event = latest_events.get(document.id)
        effective_status, worker_stopped = resolve_document_status_from_activity(
            document,
            latest_event,
            document.id in active_workers,
        )
        error = (
            document_failure_message(document, latest_event, worker_stopped)
            if effective_status == FileStatus.FAILED.value
            else None
        )
        message = (
            error
            or (latest_event.message if latest_event and latest_event.message else None)
            or (
                "Document processing and indexing completed"
                if effective_status == FileStatus.COMPLETED.value
                else "Document is being processed"
            )
        )
        items.append(
            HistoryDocumentItem(
                document_id=document.id,
                original_filename=document.original_filename,
                workspace_id=document.workspace_id,
                workspace_name=workspace_name,
                created_at=document.created_at,
                status=effective_status,
                stage=latest_event.stage if latest_event else None,
                step=latest_event.step if latest_event else None,
                message=message,
                page_number=latest_event.page_number if latest_event else None,
                total_pages=latest_event.total_pages if latest_event else None,
                error=error,
            )
        )

    return DocumentHistoryListResponse(
        items=items,
        next_cursor=page_rows[-1][0].id if len(rows) > limit else None,
    )


@router.get("/documents/{document_id}/history", response_model=DocumentHistoryResponse)
@router.get("/history/{document_id}", response_model=DocumentHistoryResponse)
async def get_document_history(
    document_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> DocumentHistoryResponse:
    """Return a document's processing events newest first."""
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    events = select(DocumentEventModel).where(
        DocumentEventModel.document_id == document_id
    )
    events = events.order_by(
        DocumentEventModel.created_at.desc(), DocumentEventModel.id.desc()
    )
    if cursor is None and document.status == FileStatus.FILE_UPLOADED.value:
        latest = await db.scalar(events.limit(1))
        if await reconcile_replacement_start_failure(db, document, latest) is not None:
            await db.commit()
    if cursor is not None:
        previous = await db.scalar(events.where(DocumentEventModel.id == cursor))
        if previous is None:
            raise HTTPException(
                status_code=400, detail="Invalid document history cursor"
            )
        events = events.where(
            tuple_(DocumentEventModel.created_at, DocumentEventModel.id)
            < (previous.created_at, previous.id)
        )
    rows = (await db.scalars(events.limit(limit + 1))).all()
    return DocumentHistoryResponse(
        document_id=document_id,
        events=[DocumentHistoryEvent.model_validate(event) for event in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
