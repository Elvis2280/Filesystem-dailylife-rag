"""Ollama-backed answer generation for chat requests."""

import asyncio
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import settings
from app.core.prompts import CHAT_AGENT_PROMPT
from app.services.ai.model_preferences import ModelRole, get_model_name_async
from app.services.ai.ollama_client import (
    OllamaClient,
    OllamaTimeoutError,
    OllamaTransientError,
)

logger = logging.getLogger("memory_rag.chat_agent")

GENERATION_ATTEMPTS = 2
GENERATION_ATTEMPT_SECONDS = 60
ANSWER_TOKEN_LIMIT = 256
RETRY_DELAY_SECONDS = 1


class EmptyAgentResponseError(RuntimeError):
    """Raised when the agent returns no usable answer."""


class _GroundedAnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    source_ids: list[str]


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str
    source_ids: list[str]


def _parse_grounded_answer(raw_answer: str) -> _GroundedAnswerPayload:
    if not isinstance(raw_answer, str):
        raise EmptyAgentResponseError("The chat agent returned no text response")

    text = raw_answer.strip()
    if text.startswith(("```json\n", "```\n")) and text.endswith("```"):
        text = text.split("\n", 1)[1][:-3].strip()
    try:
        payload = _GroundedAnswerPayload.model_validate_json(text)
    except ValidationError as exc:
        raise EmptyAgentResponseError(
            "The chat agent returned an invalid grounded-answer payload"
        ) from exc
    if not payload.answer.strip():
        raise EmptyAgentResponseError("The chat agent returned an empty response")
    return payload


async def generate_answer(
    question: str,
    references: list[dict[str, str]],
    client: OllamaClient | None = None,
) -> GroundedAnswer:
    """Generate an answer grounded exclusively in labeled retrieved chunks."""
    reference = "\n\n".join(
        f"[{item['source_id']}]\n{item['text']}" for item in references
    )
    allowed_source_ids = {item["source_id"] for item in references}
    prompt = CHAT_AGENT_PROMPT.format(question=question, reference=reference)
    ollama_client = client or OllamaClient(base_url=settings.inference_url)
    model_name = await get_model_name_async(ModelRole.ANSWER)
    logger.info(
        "Generating chat answer model=%s references=%d",
        model_name,
        len(references),
    )
    for attempt in range(1, GENERATION_ATTEMPTS + 1):
        try:
            try:
                async with asyncio.timeout(GENERATION_ATTEMPT_SECONDS):
                    raw_answer = await ollama_client.generate_async(
                        model=model_name,
                        prompt=prompt,
                        num_predict=ANSWER_TOKEN_LIMIT,
                        response_format=(
                            _GroundedAnswerPayload.model_json_schema()
                            if attempt == 1
                            else None
                        ),
                    )
            except TimeoutError as exc:
                raise OllamaTimeoutError(
                    f"Chat generation attempt exceeded {GENERATION_ATTEMPT_SECONDS} seconds"
                ) from exc
            parsed_answer = _parse_grounded_answer(raw_answer)
            logger.info(
                "Chat answer generation completed model=%s attempt=%d output_chars=%d",
                model_name,
                attempt,
                len(raw_answer) if isinstance(raw_answer, str) else 0,
            )
            break
        except (OllamaTransientError, EmptyAgentResponseError) as exc:
            if attempt >= GENERATION_ATTEMPTS:
                raise
            logger.warning(
                "Chat model '%s' attempt %d/%d failed (%s: %s); "
                "retrying without constrained decoding",
                model_name,
                attempt,
                GENERATION_ATTEMPTS,
                type(exc).__name__,
                exc,
            )
            await asyncio.sleep(RETRY_DELAY_SECONDS)
    answer = parsed_answer.answer.strip()

    source_ids = list(
        dict.fromkeys(
            source_id
            for source_id in parsed_answer.source_ids
            if source_id in allowed_source_ids
        )
    )
    if not source_ids:
        answer = "The available information is insufficient to answer this question."

    return GroundedAnswer(answer=answer, source_ids=source_ids)
