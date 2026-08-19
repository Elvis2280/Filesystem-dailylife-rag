"""Async Ollama client for FastAPI health checks and non-blocking calls.

This module is used in async contexts (FastAPI event handlers, route handlers).
Provides a generic generate_async() method that accepts model, prompt, and image
as parameters — callers are responsible for prompt engineering and model selection.
For synchronous calls in Celery workers, see app.services.ai.ollama_sync.
"""

import httpx

from app.core.config import settings
from app.schemas.ollama import OllamaStatusResponse


class OllamaClient:
    """Async HTTP client for Ollama server communication.

    Wraps httpx.AsyncClient for non-blocking API calls to the Ollama
    server. Used during application startup to verify model availability
    and in route handlers for async generation.

    Attributes:
        host: Ollama server hostname (default: from settings).
        port: Ollama server port (default: from settings).
        timeout: HTTP request timeout in seconds (default: from settings).
        base_url: Full base URL constructed from host:port.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: int | None = None,
    ):
        """Initialize the async Ollama client.

        Args:
            host: Ollama server hostname. Falls back to settings.OLLAMA_HOST.
            port: Ollama server port. Falls back to settings.OLLAMA_PORT.
            timeout: HTTP request timeout in seconds. Falls back to
                settings.OLLAMA_TIMEOUT.
        """
        self.host = host or settings.OLLAMA_HOST
        self.port = port or settings.OLLAMA_PORT
        self.timeout = timeout or settings.OLLAMA_TIMEOUT
        self.base_url = f"http://{self.host}:{self.port}"

    async def health_check(self) -> OllamaStatusResponse:
        """Check if Ollama server is reachable and list available models.

        Returns:
            OllamaStatusResponse with is_reachable=True and model list on success,
            or is_reachable=False with empty model list on failure.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/api/tags")
                list_models = response.json().get("models", [])
                return OllamaStatusResponse(
                    is_reachable=True,
                    available_models=[m["name"] for m in list_models],
                )
            except Exception:
                return OllamaStatusResponse(
                    is_reachable=False,
                    available_models=[],
                )

    async def generate_async(
        self,
        model: str,
        prompt: str,
        image_base64: str | None = None,
        num_ctx: int = 16384,
        num_predict: int = 2048,
        temperature: float = 0,
    ) -> str:
        """Send an async chat request to Ollama with model, prompt, and optional image.

        Uses deterministic settings (temperature=0, generous context window)
        for reliable results. The caller is responsible for prompt
        engineering and model selection.

        Args:
            model: Ollama model name (e.g. "glm-ocr:latest").
            prompt: Text prompt instructing the model.
            image_base64: Base64-encoded image string. If None, a text-only
                request is sent.

        Returns:
            Generated text response from the model.

        Raises:
            RuntimeError: If the request fails.
        """
        message = {"role": "user", "content": prompt}
        if image_base64 is not None:
            message["images"] = [image_base64]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": model,
                        "stream": False,
                        "messages": [message],
                        "think": False,
                        "options": {
                            "num_ctx": num_ctx,
                            "num_predict": num_predict,
                            "temperature": temperature,
                        },
                    },
                )
                response.raise_for_status()
                return response.json().get("message", {}).get("content", "")
            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"Ollama generation failed (HTTP error {e.response.status_code}): {e.response.text}"
                ) from e
            except Exception as e:
                raise RuntimeError(f"Ollama generation failed: {e}") from e


def get_ollama_client() -> OllamaClient:
    """Dependency function to provide an instance of OllamaClient."""
    return OllamaClient()
