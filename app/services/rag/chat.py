import logging

from app.services.rag.embedding import embedding
from app.services.rag.qdrant_client import search_embeddings

logger = logging.getLogger("memory_rag.chat")

NO_RELATED_DATA_MESSAGE = (
    "No data related found, upload the relevant information and try again"
)


class NoResultsError(Exception):
    """Raised when a vector search returns no results."""


def search_data(
    message: str,
    workspace_id: str,
    top_k: int = 3,
) -> list[dict]:
    """Search the vector store for data relevant to a chat message.

    Generates an embedding for the message with bge-m3 and runs a
    vector search restricted to the given workspace.

    Args:
        message: The user's question.
        workspace_id: Workspace to scope the search to.
        top_k: Number of results to return.

    Returns:
        A list of raw result dicts from Qdrant.

    Raises:
        ValueError: If the message is empty or shorter than 6 characters.
        RuntimeError: If embedding generation or the Qdrant search fails.
        NoResultsError: If no matching data was found.
    """
    if not message or not message.strip():
        logger.error("Search called with an empty message")
        raise ValueError("Message must not be empty")
    if len(message.strip()) < 6:
        logger.error("Search called with a message shorter than 6 characters")
        raise ValueError("Message must be at least 6 characters long")

    try:
        query_vector = embedding([message])[0]
    except RuntimeError as e:
        logger.error("Embedding failed for message: %s", e)
        raise

    results = search_embeddings(query_vector, workspace_id, limit=top_k)
    if not results:
        logger.info("No results found for message in workspace %s", workspace_id)
        raise NoResultsError(NO_RELATED_DATA_MESSAGE)

    return results
