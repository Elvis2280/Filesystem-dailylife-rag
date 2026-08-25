"""Application service for workspace-scoped grounded chat."""

import asyncio
from dataclasses import dataclass
from typing import Any

from app.services.chat.agent import generate_answer
from app.services.rag.chat import (
    NO_RELATED_DATA_MESSAGE,
    NoResultsError,
    search_data,
)


class InvalidChatMessageError(ValueError):
    """Raised when a chat message is empty or too short."""


class InvalidChatContextError(RuntimeError):
    """Raised when a search result cannot provide agent context."""


@dataclass(frozen=True, slots=True)
class ChatAnswer:
    """Generated answer and the raw top matches used by the endpoint."""

    response: str
    matches: list[dict[str, Any]]


async def answer_chat(
    message: str,
    workspace_id: str,
    top_k: int = 3,
) -> ChatAnswer:
    """Retrieve workspace matches and generate a grounded chat answer."""
    normalized_message = message.strip()
    if len(normalized_message) < 6:
        raise InvalidChatMessageError("Message must be at least 6 characters long")

    matches = await asyncio.to_thread(
        search_data,
        normalized_message,
        workspace_id,
        top_k,
    )
    if not matches:
        raise NoResultsError(NO_RELATED_DATA_MESSAGE)

    first_payload = matches[0].get("payload") or {}
    reference = str(first_payload.get("text") or "").strip()
    if not reference:
        raise InvalidChatContextError(
            "The top matching result does not contain searchable text"
        )

    response = await generate_answer(normalized_message, reference)
    return ChatAnswer(response=response, matches=matches[:top_k])


__all__ = [
    "ChatAnswer",
    "InvalidChatContextError",
    "InvalidChatMessageError",
    "NoResultsError",
    "answer_chat",
]
