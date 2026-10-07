"""Ollama-backed answer generation for chat requests."""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import settings
from app.core.prompts import CHAT_AGENT_PROMPT
from app.services.ai.ollama_client import OllamaClient


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
    ollama_client = client or OllamaClient()
    raw_answer = await ollama_client.generate_async(
        model=settings.OLLAMA_MODEL_AGENT,
        prompt=prompt,
        think=True,
        response_format=_GroundedAnswerPayload.model_json_schema(),
    )
    if not isinstance(raw_answer, str):
        raise EmptyAgentResponseError("The chat agent returned no text response")

    try:
        parsed_answer = _GroundedAnswerPayload.model_validate_json(raw_answer)
    except ValidationError as exc:
        raise EmptyAgentResponseError(
            "The chat agent returned an invalid grounded-answer payload"
        ) from exc

    answer = parsed_answer.answer.strip()
    if not answer:
        raise EmptyAgentResponseError("The chat agent returned an empty response")

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
