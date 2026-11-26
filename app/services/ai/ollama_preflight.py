"""Deployment preflight for a host-provided Ollama service."""

import asyncio
import logging

from app.core.config import settings
from app.services.ai.model_names import model_is_available
from app.services.ai.model_preferences import (
    ensure_model_preferences_storage,
    required_model_names,
)
from app.services.ai.ollama_client import OllamaClient

logger = logging.getLogger("memory_rag.ollama_preflight")

PREFLIGHT_ATTEMPTS = 30
PREFLIGHT_DELAY_SECONDS = 5


async def check_ollama() -> None:
    """Wait for the configured Ollama endpoint and validate required models."""
    ensure_model_preferences_storage()
    client = OllamaClient(timeout=10)

    for attempt in range(1, PREFLIGHT_ATTEMPTS + 1):
        health = await client.health_check()
        if health.is_reachable:
            missing_models = sorted(
                model_name
                for model_name in required_model_names()
                if not model_is_available(model_name, set(health.available_models))
            )
            if missing_models:
                raise RuntimeError(
                    "Ollama is reachable, but these selected models are missing: "
                    + ", ".join(missing_models)
                    + ". Install them on the Ollama host or change the selections "
                    "in the model preferences table."
                )

            logger.info(
                "Ollama is ready at %s with %d required model(s)",
                settings.OLLAMA_URL,
                len(required_model_names()),
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
