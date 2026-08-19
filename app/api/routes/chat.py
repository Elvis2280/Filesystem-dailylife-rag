import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.workspace import WorkspaceModel
from app.services.rag.chat import NoResultsError, search_data

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


class ChatResponse(BaseModel):
    message_received: bool
    message: str
    results: list[dict] = Field(default_factory=list)


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Receive a chat message and search the vector store.

    Embeds the message with bge-m3 and returns the top matching chunks
    from Qdrant scoped to the given workspace.
    """
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
        results = await asyncio.to_thread(search_data, request.message, workspace_id)
    except NoResultsError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    return ChatResponse(
        message_received=True,
        message=request.message,
        results=results,
    )
