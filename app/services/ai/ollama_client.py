"""Async Ollama client for FastAPI health checks and non-blocking calls.

This module is used exclusively in async contexts (FastAPI event handlers,
route handlers). For synchronous OCR calls in Celery workers, see
app.services.ai.ollama_sync.
"""

import httpx

from app.core.config import settings
from app.schemas.ollama import OllamaStatusResponse


class OllamaClient:
    """Async HTTP client for Ollama server communication.

    Wraps httpx.AsyncClient for non-blocking API calls to the Ollama
    server. Used primarily during application startup to verify model
    availability.

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

    async def generate_ocr_async(self, image_base64: str) -> str:
        """Asynchronously extract text from an image using the GLM-ocr vision model.

        Args:
            image_base64: Base64-encoded image string.

        Returns:
            Extracted raw text from the image.

        Raises:
            RuntimeError: If the OCR request fails.
        """

        # TODO: Move the prompt to a constant or config if it needs to be reused or modified in the future.
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": settings.OLLAMA_MODEL_OCR,
                        "stream": False,
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    "Extract all visible text from this image exactly as it appears. "
                                    "Preserve every word, number, and symbol. "
                                    "Do not reformat, summarize, or add any commentary. "
                                    "Return only the raw extracted text."
                                ),
                                "images": [image_base64],
                            }
                        ],
                        # Deterministic output: no randomness, large context for long documents
                        "options": {
                            "num_ctx": 20480,
                            "num_predict": 2048,
                            "temperature": 0,
                        },
                    },
                )
                response.raise_for_status()
                return response.json().get("message", {}).get("content", "")
            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"OCR failed (HTTP error {e.response.status_code}): {e.response.text}"
                ) from e
            except Exception as e:
                raise RuntimeError(
                    f"OCR failed (GLM model unavailable or error): {e}"
                ) from e


def get_ollama_client() -> OllamaClient:
    """Dependency function to provide an instance of OllamaClient."""
    return OllamaClient()
