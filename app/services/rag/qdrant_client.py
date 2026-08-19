import logging
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings

logger = logging.getLogger("memory_rag.qdrant")

COLLECTION_NAME = "documents"


def get_qdrant_client() -> QdrantClient:
    """Build a synchronous Qdrant client from settings."""
    return QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
    )


def ensure_collection(
    client: QdrantClient,
    vector_size: int,
    collection_name: str = COLLECTION_NAME,
) -> None:
    """Create the collection if it does not already exist."""
    if client.collection_exists(collection_name):
        logger.info("Collection '%s' already exists", collection_name)
        return
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    logger.info(
        "Created collection '%s' with vector size %d", collection_name, vector_size
    )


def _point_id(
    document_id: str,
    page_number: int,
    language: str,
    chunk_index: int,
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"{document_id}:{page_number}:{language}:{chunk_index}",
        )
    )


def upsert_embeddings(
    document_id: str,
    workspace_id: str,
    page_number: int,
    language: str,
    texts: list[str],
    vectors: list[list[float]],
    raw_ocr: str,
    japanese_text: str,
    collection_name: str = COLLECTION_NAME,
) -> None:
    """Save English chunk embeddings into Qdrant with a reference payload.

    One point is created per chunk with a deterministic id so retrying a
    document does not duplicate points.

    Raises:
        ValueError: If no vectors are provided or the texts/vectors lengths differ.
        RuntimeError: If the collection setup or upsert fails.
    """
    if not vectors or not texts:
        logger.error("Upsert called without texts or vectors")
        raise ValueError("No texts or vectors provided for upsert")
    if len(texts) != len(vectors):
        logger.error(
            "Upsert received %d texts but %d vectors", len(texts), len(vectors)
        )
        raise ValueError("Texts and vectors lengths must match")

    client = get_qdrant_client()
    try:
        ensure_collection(client, len(vectors[0]), collection_name)
    except Exception as e:
        logger.error("Failed to set up collection '%s': %s", collection_name, e)
        raise RuntimeError(f"Qdrant collection setup failed: {e}") from e

    points = [
        PointStruct(
            id=_point_id(document_id, page_number, language, idx),
            vector=vector,
            payload={
                "document_id": document_id,
                "workspace_id": workspace_id,
                "page_number": page_number,
                "chunk_index": idx,
                "language": language,
                "text": text,
                "raw_ocr": raw_ocr,
                "japanese_text": japanese_text,
            },
        )
        for idx, (text, vector) in enumerate(zip(texts, vectors))
    ]

    try:
        client.upsert(collection_name=collection_name, points=points)
        logger.info("Upserted %d points into '%s'", len(points), collection_name)
    except Exception as e:
        logger.error("Failed to upsert points into '%s': %s", collection_name, e)
        raise RuntimeError(f"Qdrant upsert failed: {e}") from e


def search_embeddings(
    vector: list[float],
    workspace_id: str,
    limit: int = 3,
    collection_name: str = COLLECTION_NAME,
) -> list[dict]:
    """Search the closest stored vectors for a given workspace.

    Args:
        vector: Query embedding vector.
        workspace_id: Only points belonging to this workspace are returned.
        limit: Maximum number of results to return (top-k).

    Returns:
        A list of raw result dicts with "id", "score", and "payload".

    Raises:
        ValueError: If no query vector is provided.
        RuntimeError: If the search fails.
    """
    if not vector:
        logger.error("Search called without a query vector")
        raise ValueError("No vector provided for search")

    client = get_qdrant_client()
    try:
        response = client.query_points(
            collection_name=collection_name,
            query=vector,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="workspace_id",
                        match=MatchValue(value=workspace_id),
                    )
                ]
            ),
            limit=limit,
        )
    except Exception as e:
        logger.error("Failed to search collection '%s': %s", collection_name, e)
        raise RuntimeError(f"Qdrant search failed: {e}") from e

    return [
        {
            "id": str(point.id),
            "score": point.score,
            "payload": point.payload or {},
        }
        for point in response.points
    ]
