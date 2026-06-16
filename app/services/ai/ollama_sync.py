"""Synchronous Ollama client for Celery workers.

Uses the official ollama Python library for straightforward sync API calls.
This module is the sync counterpart to app.services.ai.ollama_client,
designed for use in blocking contexts (Celery tasks, not FastAPI routes).
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

    def generate_ocr(self, image_file: str | bytes) -> str:
        """Extract text from image using GLM-ocr vision model.

        Sends the image to the Ollama server with a prompt instructing
        the model to extract text verbatim. Uses deterministic settings
        (temperature=0, generous context window) for reliable results.

        Args:
            image_file: Path to the image file to OCR or the image data as bytes.

        Returns:
            Extracted raw text from the image.

        Raises:
            RuntimeError: If GLM model is unavailable or returns an error.
        """
        try:
            response = self._client.chat(
                model=settings.OLLAMA_MODEL_OCR,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "You are an expert document analysis system. Your task is to perform a strict, top-to-bottom reading "
                            "of the provided page image and extract ALL visible text. Do not omit anything.\n\n"
                            "Structure your output sequentially following the visual layout from top to bottom:\n\n"
                            "1. [TOP TEXT]: Transcribe all initial plain document text, titles, or headers.\n"
                            "2. [IMAGE/POSTER CONTENT]: Look inside the embedded graphic/poster. Transcribe all text found within it, "
                            "including vertical text, actor names, titles, dates, and media formats.\n"
                            "3. [LINKS & NAVIGATION]: Transcribe all links, standalone anchor texts, or navigation items below the image.\n"
                            "4. [TABLE CONTENT]: Detect the data table. Reconstruct it exactly as a Markdown table with its columns and rows.\n\n"
                            "Strict Rule: Scan the entire canvas. Do not stop writing until you have processed the elements below the image, "
                            "especially the links and the final data table. Output only the transcribed content organized by these sections."
                        ),
                        "images": [image_file],
                    }
                ],
                # Deterministic output: no randomness, large context for long documents
                options={"num_ctx": 20480, "num_predict": 2048, "temperature": 0},
            )
            return str(response.message.content)
        except Exception as e:
            raise RuntimeError(f"OCR failed (GLM model unavailable or error): {e}")
