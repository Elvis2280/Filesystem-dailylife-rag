from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.constant import FilePipelineStage
from app.models.document_event import DocumentEventModel


def add_document_event(
    db_session: Session,
    *,
    document_id: uuid.UUID | str,
    workspace_id: uuid.UUID | str,
    status: str,
    stage: FilePipelineStage | str | None = None,
    step: str | None = None,
    message: str | None = None,
    page_number: int | None = None,
    total_pages: int | None = None,
    document_split_id: uuid.UUID | str | None = None,
    translation_id: uuid.UUID | str | None = None,
) -> DocumentEventModel:
    event = DocumentEventModel(
        document_id=document_id,
        workspace_id=workspace_id,
        document_split_id=document_split_id,
        translation_id=translation_id,
        status=status,
        stage=stage.value if isinstance(stage, FilePipelineStage) else stage,
        step=step,
        message=message,
        page_number=page_number,
        total_pages=total_pages,
    )
    db_session.add(event)
    return event
