"""Synchronous Ollama client for Celery workers.

Uses the official ollama Python library for straightforward sync API calls.
This module is the sync counterpart to app.services.ai.ollama_client,
designed for use in blocking contexts (Celery tasks, not FastAPI routes).
Provides a generic generate() method that accepts model, prompt, and image
as parameters — callers are responsible for prompt engineering and model selection.
"""

from ollama import Client

from app.core.config import settings


class OllamaSyncClient:
    """Sync client using the official ollama Python library.

    Provides blocking API calls to the Ollama server for use within
    Celery worker tasks. The official ollama library is sync-only,
    making it ideal for worker processes where async I/O offers
    no benefit.

    Attributes:
        _client: Internal ollama.Client instance bound to the server URL.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
    ):
        """Initialize the sync Ollama client.

        Args:
            host: Ollama server hostname. Falls back to settings.OLLAMA_HOST.
            port: Ollama server port. Falls back to settings.OLLAMA_PORT.
        """
        host = host or settings.OLLAMA_HOST
        port = port or settings.OLLAMA_PORT
        base_url = f"http://{host}:{port}"
        self._client = Client(
            host=base_url,
            timeout=settings.OLLAMA_TIMEOUT,
        )

    def generate(
        self, model: str, prompt: str, image: str | bytes | None = None
    ) -> str:
        """Send a chat request to Ollama with model, prompt, and optional image.

        Uses deterministic settings (temperature=0, generous context window)
        for reliable results. The caller is responsible for prompt
        engineering and model selection.

        Args:
            model: Ollama model name (e.g. "glm-ocr:latest").
            prompt: Text prompt instructing the model.
            image: Path to the image file or image data as bytes. If None,
                a text-only request is sent.

        Returns:
            Generated text response from the model.

        Raises:
            RuntimeError: If the model is unavailable or returns an error.
        """
        message = {"role": "user", "content": prompt}
        if image is not None:
            message["images"] = [image]

        try:
            response = self._client.chat(
                model=model,
                messages=[message],
                options={
                    "num_ctx": 32768,
                    "num_predict": 8192,
                    "temperature": 0,
                    "stop": ["```"],
                },
            )
            return str(response.message.content)
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {e}")
