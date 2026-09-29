"""Deployment preflight for a host-provided Ollama service."""

import asyncio
import logging

from app.core.config import settings
from app.services.ai.ollama_client import OllamaClient

logger = logging.getLogger("memory_rag.ollama_preflight")

PREFLIGHT_ATTEMPTS = 30
PREFLIGHT_DELAY_SECONDS = 5


def required_models() -> set[str]:
    """Return the unique Ollama models required by the application."""
    return {
        settings.OLLAMA_MODEL_OCR,
        settings.OLLAMA_MODEL_FORMAT,
        settings.OLLAMA_MODEL_TRANSLATION,
        settings.OLLAMA_MODEL_CLEANER,
        settings.OLLAMA_MODEL_EMBEDDING,
        settings.OLLAMA_MODEL_AGENT,
    }


async def check_ollama() -> None:
    """Wait for the configured Ollama endpoint and validate required models."""
    client = OllamaClient(timeout=10)

    for attempt in range(1, PREFLIGHT_ATTEMPTS + 1):
        health = await client.health_check()
        if health.is_reachable:
            available_models = set(health.available_models)
            missing_models = sorted(required_models() - available_models)
            if missing_models:
                raise RuntimeError(
                    "Ollama is reachable, but these configured models are missing: "
                    + ", ".join(missing_models)
                    + ". Run 'ollama list' on the host and update the Coolify "
                    "OLLAMA_MODEL_* variables to match the installed names."
                )

            logger.info(
                "Ollama is ready at %s with %d required model(s)",
                settings.OLLAMA_URL,
                len(required_models()),
            )
            return

        if attempt < PREFLIGHT_ATTEMPTS:
            logger.warning(
                "Ollama is not reachable at %s (attempt %d/%d); retrying",
                settings.OLLAMA_URL,
                attempt,
                PREFLIGHT_ATTEMPTS,
            )
            await asyncio.sleep(PREFLIGHT_DELAY_SECONDS)

    raise RuntimeError(
        f"Ollama is not reachable at {settings.OLLAMA_URL} after "
        f"{PREFLIGHT_ATTEMPTS} attempts. Check the URL and container network access."
    )


if __name__ == "__main__":
    asyncio.run(check_ollama())
