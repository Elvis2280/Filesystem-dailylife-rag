"""Async Ollama client for FastAPI health checks and non-blocking calls.

This module is used in async contexts (FastAPI event handlers, route handlers).
Provides a generic generate_async() method that accepts model, prompt, and image
as parameters — callers are responsible for prompt engineering and model selection.
For synchronous calls in Celery workers, see app.services.ai.ollama_sync.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.ollama import OllamaStatusResponse

logger = logging.getLogger("memory_rag.ollama")


class OllamaTransientError(RuntimeError):
    """Raised for Ollama failures that are reasonable to retry once."""


class OllamaTimeoutError(OllamaTransientError):
    """Raised when Ollama does not respond within the configured timeout."""


class OllamaGenerationError(RuntimeError):
    """Raised when Ollama rejects a generation request permanently."""


class OllamaClient:
    """Async HTTP client for Ollama server communication.

    Wraps httpx.AsyncClient for non-blocking API calls to the Ollama
    server. Used during application startup to verify model availability
    and in route handlers for async generation.

    Attributes:
        host: Ollama server hostname (default: from settings).
        port: Ollama server port (default: from settings).
        timeout: HTTP request timeout in seconds (default: from settings).
        base_url: Full Ollama base URL, including its scheme.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: int | None = None,
        base_url: str | None = None,
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
        if base_url is not None:
            self.base_url = base_url.rstrip("/")
        elif host is not None or port is not None:
            self.base_url = f"http://{self.host}:{self.port}"
        else:
            self.base_url = settings.OLLAMA_URL

    async def health_check(self) -> OllamaStatusResponse:
        """Check if Ollama server is reachable and list available models.

        Returns:
            OllamaStatusResponse with is_reachable=True and model list on success,
            or is_reachable=False with empty model list on failure.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
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

    async def list_models(self) -> list[dict[str, Any]]:
        """Return Ollama's installed model records from ``/api/tags``."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            records = response.json().get("models", [])
            return [record for record in records if isinstance(record, dict)]

    async def show_model(self, model: str) -> dict[str, Any]:
        """Return capabilities and metadata for one installed model."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/show",
                json={"model": model},
            )
            response.raise_for_status()
            details = response.json()
            if not isinstance(details, dict):
                raise RuntimeError("Ollama returned invalid model details")
            return details

    async def embed(self, model: str, message: str) -> list[float]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": model, "input": [message]},
                )
                response.raise_for_status()
                return response.json()["embeddings"][0]
            except httpx.HTTPStatusError as exc:
                _raise_ollama_http_error(exc, operation="embedding")
            except httpx.TimeoutException as exc:
                raise OllamaTimeoutError("Ollama chat embedding timed out") from exc
            except httpx.TransportError as exc:
                raise OllamaTransientError(
                    "Could not reach Ollama for chat embedding"
                ) from exc
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise OllamaGenerationError(
                    "Ollama returned an invalid embedding"
                ) from exc

    async def generate_async(
        self,
        model: str,
        prompt: str,
        image_base64: str | None = None,
        num_ctx: int = 16384,
        num_predict: int = 2048,
        temperature: float = 0,
        think: bool = False,
        response_format: str | dict[str, Any] | None = None,
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
            think: Whether Ollama should enable the model's thinking mode.

        Returns:
            Generated text response from the model.

        Raises:
            RuntimeError: If the request fails.
        """
        message = {"role": "user", "content": prompt}
        if image_base64 is not None:
            message["images"] = [image_base64]

        request_data: dict[str, Any] = {
            "model": model,
            "stream": False,
            "messages": [message],
            "think": False,
            "options": {
                "num_ctx": num_ctx,
                "num_predict": num_predict,
                "temperature": temperature,
            },
        }
        if response_format is not None:
            request_data["format"] = response_format

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=request_data,
                )
                response.raise_for_status()
                payload = response.json()
                logger.info(
                    "Ollama generation model=%s load_ns=%s prompt_eval_ns=%s eval_ns=%s output_tokens=%s",
                    model,
                    payload.get("load_duration"),
                    payload.get("prompt_eval_duration"),
                    payload.get("eval_duration"),
                    payload.get("eval_count"),
                )
                return payload.get("message", {}).get("content", "")
            except httpx.HTTPStatusError as e:
                _raise_ollama_http_error(e, operation="generation")
            except httpx.TimeoutException as e:
                raise OllamaTimeoutError(
                    f"Ollama generation timed out after {self.timeout} seconds"
                ) from e
            except httpx.TransportError as e:
                raise OllamaTransientError(
                    f"Could not reach Ollama for generation: {e}"
                ) from e
            except Exception as e:
                raise OllamaGenerationError(f"Ollama generation failed: {e}") from e


def _raise_ollama_http_error(
    error: httpx.HTTPStatusError,
    operation: str = "request",
) -> None:
    status_code = error.response.status_code
    error_type = (
        OllamaTransientError
        if status_code in {408, 425, 429} or status_code >= 500
        else OllamaGenerationError
    )
    raise error_type(
        f"Ollama {operation} failed (HTTP error {status_code}): {error.response.text}"
    ) from error


def get_ollama_client() -> OllamaClient:
    """Dependency function to provide an instance of OllamaClient."""
    return OllamaClient()
