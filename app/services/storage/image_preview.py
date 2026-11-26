"""Resolve split images for preview and download routes."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_split import DocumentSplitModel


class ImagePreviewNotFound(LookupError):
    """Raised when the requested split image does not exist."""


async def resolve_split_image(
    split_id: uuid.UUID,
    db: AsyncSession,
) -> DocumentSplitModel:
    """Return one split image by its database ID."""

    result = await db.execute(
        select(DocumentSplitModel).where(DocumentSplitModel.id == split_id)
    )
    split = result.scalar_one_or_none()
    if split is None:
        raise ImagePreviewNotFound
    return split
