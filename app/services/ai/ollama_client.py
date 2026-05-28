"""Async Ollama client for FastAPI health checks and non-blocking calls."""

import httpx

from app.core.config import settings


class OllamaClient:
    """Async HTTP client for Ollama server communication."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: int | None = None,
    ):
        self.host = host or settings.OLLAMA_HOST
        self.port = port or settings.OLLAMA_PORT
        self.timeout = timeout or settings.OLLAMA_TIMEOUT
        self.base_url = f"http://{self.host}:{self.port}"

    async def health_check(self) -> bool:
        """Check if Ollama server is reachable."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
            except Exception:
                return False

    async def is_model_available(self, model_name: str) -> bool:
        """Check if a specific model is pulled and available."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/api/tags")
                data = response.json()
                models = [m["name"] for m in data.get("models", [])]
                return model_name in models
            except Exception:
                return False
