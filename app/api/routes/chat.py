from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
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


class ChatMatch(BaseModel):
    label: str
    english: str
    japanese: str


class ChatResponse(BaseModel):
    original_message: str
    response: str
    raw_response: list[ChatMatch] = Field(default_factory=list)


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

    return ChatResponse(
        original_message=request.message,
        response=chat_answer.response,
        raw_response=[
            ChatMatch(
                label=f"A{index}",
                english=str((match.get("payload") or {}).get("text") or ""),
                japanese=str((match.get("payload") or {}).get("japanese_text") or ""),
            )
            for index, match in enumerate(chat_answer.matches, start=1)
        ],
    )
