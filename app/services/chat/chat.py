"""Application service for workspace-scoped grounded chat."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.ai.ollama_client import OllamaGenerationError, OllamaTransientError
from app.services.chat.agent import EmptyAgentResponseError, generate_answer
from app.services.rag.chat import (
    NO_RELATED_DATA_MESSAGE,
    NoResultsError,
    search_data,
)

logger = logging.getLogger("memory_rag.chat_service")
RETRIEVAL_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 1
CITATION_RESERVE_SECONDS = 5
EXCERPT_MAX_CHARS = 400


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
    *,
    deadline: float | None = None,
) -> ChatAnswer:
    """Retrieve workspace matches and generate a grounded chat answer."""
    normalized_message = message.strip()
    if len(normalized_message) < 6:
        raise InvalidChatMessageError("Message must be at least 6 characters long")

    logger.info("Starting chat retrieval workspace=%s", workspace_id)
    for attempt in range(1, RETRIEVAL_ATTEMPTS + 1):
        try:
            matches = await search_data(
                normalized_message,
                workspace_id,
                candidate_limit,
            )
            logger.info(
                "Chat retrieval completed workspace=%s results=%d attempt=%d",
                workspace_id,
                len(matches),
                attempt,
            )
            break
        except RuntimeError:
            if attempt >= RETRIEVAL_ATTEMPTS:
                raise
            logger.warning(
                "Chat retrieval failed for workspace=%s (attempt %d/%d); "
                "retrying once in the backend",
                workspace_id,
                attempt,
                RETRIEVAL_ATTEMPTS,
                exc_info=True,
            )
            await asyncio.sleep(RETRY_DELAY_SECONDS)
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

    references = [
        {
            "source_id": str(match["source_id"]),
            "text": str((match.get("payload") or {}).get("text") or ""),
        }
        for match in context_matches
    ]
    generation_deadline = (
        deadline - CITATION_RESERVE_SECONDS if deadline is not None else None
    )
    try:
        async with asyncio.timeout_at(generation_deadline):
            generated = await generate_answer(normalized_message, references)
    except (
        TimeoutError,
        OllamaTransientError,
        OllamaGenerationError,
        EmptyAgentResponseError,
    ) as exc:
        logger.warning(
            "Returning source excerpts for workspace=%s after chat generation failed: %s: %s",
            workspace_id,
            type(exc).__name__,
            exc,
        )
        excerpts = []
        for reference in references[:2]:
            excerpt = " ".join(reference["text"].split())
            if len(excerpt) > EXCERPT_MAX_CHARS:
                excerpt = excerpt[:EXCERPT_MAX_CHARS].rstrip() + "…"
            excerpts.append(f"[{reference['source_id']}] {excerpt}")
        return ChatAnswer(
            response=(
                "I couldn’t finish generating a full answer. Here are the most "
                "relevant excerpts I found:\n\n" + "\n\n".join(excerpts)
            ),
            matches=context_matches[: len(excerpts)],
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
