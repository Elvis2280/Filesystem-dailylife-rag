import logging

from app.core.config import settings
from app.services.ai.ollama_sync import OllamaSyncClient

logger = logging.getLogger("memory_rag.embedding")


def embedding(texts: list[str]) -> list[list[float]]:
    """Generate bge-m3 embeddings for a batch of texts via Ollama.

    Args:
        texts: List of text chunks to embed.

    Returns:
        List of embedding vectors, one per input text.

    Raises:
        ValueError: If no text was provided or a text is empty.
        RuntimeError: If the embedding request to Ollama fails.
    """
    if not texts:
        logger.error("Embedding called with no text")
        raise ValueError("No text provided for embedding")

    for text in texts:
        if not text.strip():
            logger.error("Embedding called with an empty text chunk")
            raise ValueError("Embedding received an empty text chunk")

    client = OllamaSyncClient()
    try:
        return client.embed(
            model=settings.OLLAMA_MODEL_EMBEDDING,
            input=texts,
        )
    except RuntimeError as e:
        logger.error("Embedding failed: %s", e)
        raise
