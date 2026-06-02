"""Async Ollama client for FastAPI health checks and non-blocking calls.

This module is used exclusively in async contexts (FastAPI event handlers,
route handlers). For synchronous OCR calls in Celery workers, see
app.services.ai.ollama_sync.
"""

import httpx

from app.core.config import settings


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

    async def health_check(self) -> bool:
        """Check if Ollama server is reachable.

        Sends a GET request to the /api/tags endpoint to verify
        connectivity. Returns True if the server responds with 200.

        Returns:
            True if the Ollama server is reachable, False otherwise.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
            except Exception:
                return False

    async def is_model_available(self, model_name: str) -> bool:
        """Check if a specific model is pulled and available on the server.

        Fetches the list of available models from /api/tags and checks
        if the requested model name is present.

        Args:
            model_name: The name of the Ollama model to check (e.g., 'glm-ocr').

        Returns:
            True if the model is available, False otherwise.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/api/tags")
                data = response.json()
                models = [m["name"] for m in data.get("models", [])]
                return model_name in models
            except Exception:
                return False
