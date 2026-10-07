"""Application service for workspace-scoped grounded chat."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.chat.agent import generate_answer
from app.services.rag.chat import (
    NO_RELATED_DATA_MESSAGE,
    NoResultsError,
    search_data,
)

logger = logging.getLogger("memory_rag.chat_service")


class InvalidChatMessageError(ValueError):
    """Raised when a chat message is empty or too short."""


class InvalidChatContextError(RuntimeError):
    """Raised when a search result cannot provide agent context."""


@dataclass(frozen=True, slots=True)
class ChatAnswer:
    """Generated answer and the cited matches used by the endpoint."""

    response: str
    matches: list[dict[str, Any]]


async def answer_chat(
    message: str,
    workspace_id: str,
    candidate_limit: int = 20,
    context_limit: int = 6,
) -> ChatAnswer:
    """Retrieve workspace matches and generate a grounded chat answer."""
    normalized_message = message.strip()
    if len(normalized_message) < 6:
        raise InvalidChatMessageError("Message must be at least 6 characters long")

    matches = await asyncio.to_thread(
        search_data,
        normalized_message,
        workspace_id,
        candidate_limit,
    )
    if not matches:
        raise NoResultsError(NO_RELATED_DATA_MESSAGE)

    context_limit = min(max(context_limit, 1), 6)
    context_matches: list[dict[str, Any]] = []
    seen_chunks: set[tuple[str, int | None, str]] = set()
    for match in matches:
        payload = match.get("payload") or {}
        text = str(payload.get("text") or "").strip()
        normalized_text = " ".join(text.split())
        chunk_identity = (
            str(payload.get("document_id") or ""),
            payload.get("page_number"),
            normalized_text,
        )
        if not text or chunk_identity in seen_chunks:
            continue
        seen_chunks.add(chunk_identity)
        source_id = f"S{len(context_matches) + 1}"
        context_matches.append({**match, "source_id": source_id})
        if len(context_matches) >= context_limit:
            break

    if not context_matches:
        raise InvalidChatContextError(
            "The matching results do not contain searchable text"
        )

    generated = await generate_answer(
        normalized_message,
        [
            {
                "source_id": str(match["source_id"]),
                "text": str((match.get("payload") or {}).get("text") or ""),
            }
            for match in context_matches
        ],
    )
    context_by_id = {str(match["source_id"]): match for match in context_matches}
    cited_matches = [
        context_by_id[source_id]
        for source_id in generated.source_ids
        if source_id in context_by_id
    ]
    cited_matches.sort(key=lambda match: float(match.get("score") or 0), reverse=True)

    logger.info(
        "RAG context workspace=%s candidates=%d selected=%s cited=%s hybrid=%s",
        workspace_id,
        len(matches),
        [match["source_id"] for match in context_matches],
        [match["source_id"] for match in cited_matches],
        settings.QDRANT_USE_HYBRID,
    )
    return ChatAnswer(response=generated.answer, matches=cited_matches)


__all__ = [
    "ChatAnswer",
    "InvalidChatContextError",
    "InvalidChatMessageError",
    "NoResultsError",
    "answer_chat",
]
