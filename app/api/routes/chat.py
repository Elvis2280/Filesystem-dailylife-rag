from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.document import Document
from app.models.document_split import DocumentSplitModel
from app.models.translation import TranslationModel
from app.models.workspace import WorkspaceModel
from app.services.ai.ollama_client import OllamaTimeoutError
from app.services.chat.agent import EmptyAgentResponseError
from app.services.chat.chat import (
    InvalidChatContextError,
    InvalidChatMessageError,
    NoResultsError,
    answer_chat,
)

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    workspace_id: UUID
    message: str = Field(..., min_length=6)

    @field_validator("message")
    @classmethod
    def _message_not_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty")
        return value


class ChatSource(BaseModel):
    document_id: UUID
    page_number: int
    english_markdown_id: UUID
    japanese_markdown_id: UUID


class ChatResponse(BaseModel):
    response: str
    english_markdown_id: UUID | None
    japanese_markdown_id: UUID | None
    sources: list[ChatSource] = Field(default_factory=list)


async def _resolve_markdown_ids(
    payload: dict[str, Any],
    workspace_id: UUID,
    db: AsyncSession,
) -> tuple[UUID, UUID]:
    """Find both completed translations for the matched document page."""
    try:
        match_workspace_id = UUID(str(payload["workspace_id"]))
        document_id = UUID(str(payload["document_id"]))
        page_number = payload["page_number"]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The top matching result has invalid page metadata",
        ) from exc

    if (
        match_workspace_id != workspace_id
        or not isinstance(page_number, int)
        or isinstance(page_number, bool)
        or page_number < 1
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The top matching result has invalid page metadata",
        )

    result = await db.execute(
        select(
            DocumentSplitModel.id,
            TranslationModel.language,
            TranslationModel.id,
        )
        .select_from(TranslationModel)
        .join(
            DocumentSplitModel,
            TranslationModel.document_split_id == DocumentSplitModel.id,
        )
        .join(Document, DocumentSplitModel.document_id == Document.id)
        .where(
            TranslationModel.workspace_id == match_workspace_id,
            TranslationModel.language.in_(("EN", "JP")),
            TranslationModel.status == "completed",
            DocumentSplitModel.workspace_id == match_workspace_id,
            DocumentSplitModel.page_number == page_number,
            or_(
                Document.id == document_id,
                Document.parent_document_id == document_id,
            ),
        )
        .order_by(
            case((DocumentSplitModel.document_id == document_id, 0), else_=1),
            DocumentSplitModel.id,
        )
    )

    translations_by_split: dict[UUID, dict[str, UUID]] = {}
    for split_id, language, translation_id in result.all():
        translations_by_split.setdefault(split_id, {})[language.upper()] = (
            translation_id
        )

    for translations in translations_by_split.values():
        if "EN" in translations and "JP" in translations:
            return translations["EN"], translations["JP"]

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Markdown translations were not found for the top matching page",
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Generate a grounded answer from workspace-scoped document matches."""
    workspace_id = str(request.workspace_id)

    result = await db.execute(
        select(WorkspaceModel).where(WorkspaceModel.id == request.workspace_id)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found",
        )

    try:
        chat_answer = await answer_chat(request.message, workspace_id)
    except InvalidChatMessageError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except NoResultsError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except OllamaTimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(e),
        ) from e
    except EmptyAgentResponseError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e
    except InvalidChatContextError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    sources: list[ChatSource] = []
    seen_pages: set[tuple[str, int]] = set()
    for match in chat_answer.matches:
        payload = match.get("payload") or {}
        try:
            source_document_uuid = UUID(str(payload["document_id"]))
            source_page_number = payload["page_number"]
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="A cited result has invalid page metadata",
            )
        if not isinstance(source_page_number, int) or isinstance(
            source_page_number, bool
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="A cited result has invalid page metadata",
            )
        source_document_id = str(source_document_uuid)
        page_key = (source_document_id, source_page_number)
        if page_key in seen_pages:
            continue
        seen_pages.add(page_key)
        english_id, japanese_id = await _resolve_markdown_ids(
            payload,
            request.workspace_id,
            db,
        )
        sources.append(
            ChatSource(
                document_id=source_document_uuid,
                page_number=source_page_number,
                english_markdown_id=english_id,
                japanese_markdown_id=japanese_id,
            )
        )

    primary_source = sources[0] if sources else None

    return ChatResponse(
        response=chat_answer.response,
        english_markdown_id=(
            primary_source.english_markdown_id if primary_source else None
        ),
        japanese_markdown_id=(
            primary_source.japanese_markdown_id if primary_source else None
        ),
        sources=sources,
    )
