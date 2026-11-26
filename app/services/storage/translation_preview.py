"""Resolve translated Markdown files for preview and download routes."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.translation import TranslationModel


class TranslationPreviewNotFound(LookupError):
    """Raised when the requested translation does not exist."""


async def resolve_translation(
    translation_id: uuid.UUID,
    db: AsyncSession,
) -> TranslationModel:
    """Return one page translation by its database ID."""

    result = await db.execute(
        select(TranslationModel).where(TranslationModel.id == translation_id)
    )
    translation = result.scalar_one_or_none()
    if translation is None:
        raise TranslationPreviewNotFound
    return translation
