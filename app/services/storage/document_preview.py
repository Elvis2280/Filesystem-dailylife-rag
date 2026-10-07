"""Resolve the canonical PDF representation for a document."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


class PdfPreviewNotFound(LookupError):
    """Raised when a document has no PDF representation available."""


async def resolve_pdf_document(
    document_id: uuid.UUID,
    db: AsyncSession,
) -> Document:
    """Return the physical document row that should be rendered as PDF.

    A PDF original is its own canonical representation. For a non-PDF
    original, the only allowed representation is its workspace-local
    ``converted_pdf`` child. A converted child may also be requested directly.
    """

    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is None:
        raise PdfPreviewNotFound

    if document.file_role == "converted_pdf":
        if document.mime_type == "application/pdf":
            return document
        raise PdfPreviewNotFound

    if document.mime_type == "application/pdf":
        return document

    child_result = await db.execute(
        select(Document).where(
            Document.workspace_id == document.workspace_id,
            Document.parent_document_id == document.id,
            Document.file_role == "converted_pdf",
            Document.mime_type == "application/pdf",
        )
    )
    converted_document = child_result.scalar_one_or_none()
    if converted_document is None:
        raise PdfPreviewNotFound
    return converted_document
