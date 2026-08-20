"""Ollama-backed answer generation for chat requests."""

from app.core.config import settings
from app.core.prompts import CHAT_AGENT_PROMPT
from app.services.ai.ollama_client import OllamaClient


class EmptyAgentResponseError(RuntimeError):
    """Raised when the agent returns no usable answer."""


async def generate_answer(
    question: str,
    reference: str,
    client: OllamaClient | None = None,
) -> str:
    """Generate an answer grounded exclusively in the supplied reference."""
    prompt = CHAT_AGENT_PROMPT.format(question=question, reference=reference)
    ollama_client = client or OllamaClient()
    raw_answer = await ollama_client.generate_async(
        model=settings.OLLAMA_MODEL_AGENT,
        prompt=prompt,
        think=True,
    )
    if not isinstance(raw_answer, str):
        raise EmptyAgentResponseError("The chat agent returned no text response")

    answer = raw_answer.strip()
    if not answer:
        raise EmptyAgentResponseError("The chat agent returned an empty response")
    return answer
