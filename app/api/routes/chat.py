from fastapi import APIRouter, status
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    message_received: bool
    message: str


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
)
async def chat(request: ChatRequest) -> ChatResponse:
    """Receive a chat message and acknowledge it.

    For now it only echoes the received message back.
    """
    return ChatResponse(
        message_received=True,
        message=request.message,
    )
