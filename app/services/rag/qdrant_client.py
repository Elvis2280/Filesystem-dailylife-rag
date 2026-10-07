import logging
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from app.core.config import settings

logger = logging.getLogger("memory_rag.qdrant")

COLLECTION_NAME = "documents"
HYBRID_COLLECTION_NAME = "documents_v2"


def _is_hybrid_collection(collection_name: str) -> bool:
    return collection_name == (
        settings.QDRANT_HYBRID_COLLECTION or HYBRID_COLLECTION_NAME
    )


def get_qdrant_client() -> QdrantClient:
    """Build a synchronous Qdrant client from settings."""
    return QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
    )


def _ensure_workspace_index(client: QdrantClient, collection_name: str) -> None:
    collection = client.get_collection(collection_name)
    if "workspace_id" in (collection.payload_schema or {}):
        return
    client.create_payload_index(
        collection_name=collection_name,
        field_name="workspace_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
        wait=True,
    )


def ensure_collection(
    client: QdrantClient,
    vector_size: int,
    collection_name: str = COLLECTION_NAME,
) -> None:
    """Create a dense-only collection when needed and index its workspace key."""
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )
        logger.info(
            "Created dense collection '%s' with vector size %d",
            collection_name,
            vector_size,
        )
    _ensure_workspace_index(client, collection_name)


def ensure_hybrid_collection(
    client: QdrantClient,
    vector_size: int,
    collection_name: str = HYBRID_COLLECTION_NAME,
) -> None:
    """Create the versioned dense plus BM25 collection when needed."""
    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                )
            },
        )
        logger.info(
            "Created hybrid collection '%s' with dense vector size %d",
            collection_name,
            vector_size,
        )
    _ensure_workspace_index(client, collection_name)


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


def _workspace_filter(workspace_id: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="workspace_id",
                match=models.MatchValue(value=workspace_id),
            )
        ]
    )


def _delete_obsolete_chunks(
    client: QdrantClient,
    collection_name: str,
    document_id: str,
    page_number: int,
    chunk_count: int | None,
) -> None:
    conditions = [
        models.FieldCondition(
            key="document_id",
            match=models.MatchValue(value=document_id),
        ),
        models.FieldCondition(
            key="page_number",
            match=models.MatchValue(value=page_number),
        ),
    ]
    if chunk_count is not None:
        conditions.append(
            models.FieldCondition(
                key="chunk_index",
                range=models.Range(gte=chunk_count),
            )
        )
    client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(filter=models.Filter(must=conditions)),
        wait=True,
    )


def delete_page_embeddings(
    document_id: str,
    page_number: int,
    collection_name: str,
) -> None:
    """Remove all indexed chunks for a page that no longer has searchable text."""
    client = get_qdrant_client()
    if not client.collection_exists(collection_name):
        return
    _delete_obsolete_chunks(
        client,
        collection_name,
        document_id,
        page_number,
        chunk_count=None,
    )


def delete_document_embeddings_after_page(
    document_id: str,
    last_page_number: int,
    collection_name: str,
) -> None:
    """Remove indexed pages beyond the document's current page count."""
    client = get_qdrant_client()
    if not client.collection_exists(collection_name):
        return
    client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id),
                    ),
                    models.FieldCondition(
                        key="page_number",
                        range=models.Range(gt=last_page_number),
                    ),
                ]
            )
        ),
        wait=True,
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
    retrieval_texts: list[str] | None = None,
    document_title: str = "",
    section_titles: list[str] | None = None,
    collection_name: str = COLLECTION_NAME,
) -> None:
    """Save answer chunks and their dense or dense plus BM25 vectors."""
    if not vectors or not texts:
        raise ValueError("No texts or vectors provided for upsert")
    if len(texts) != len(vectors):
        raise ValueError("Texts and vectors lengths must match")

    retrieval_texts = retrieval_texts or texts
    section_titles = section_titles or [""] * len(texts)
    if len(retrieval_texts) != len(texts) or len(section_titles) != len(texts):
        raise ValueError("Chunk metadata lengths must match the texts length")

    client = get_qdrant_client()
    try:
        if _is_hybrid_collection(collection_name):
            ensure_hybrid_collection(client, len(vectors[0]), collection_name)
        else:
            ensure_collection(client, len(vectors[0]), collection_name)
    except Exception as exc:
        logger.error("Failed to set up collection '%s': %s", collection_name, exc)
        raise RuntimeError(f"Qdrant collection setup failed: {exc}") from exc

    points = []
    for idx, (text, vector, retrieval_text, section_title) in enumerate(
        zip(texts, vectors, retrieval_texts, section_titles)
    ):
        payload = {
            "document_id": document_id,
            "workspace_id": workspace_id,
            "page_number": page_number,
            "chunk_index": idx,
            "language": language,
            "text": text,
            "document_title": document_title,
            "section_title": section_title,
            "raw_ocr": raw_ocr,
            "japanese_text": japanese_text,
        }
        point_vector: list[float] | dict[str, object] = vector
        if _is_hybrid_collection(collection_name):
            point_vector = {
                "dense": vector,
                "bm25": models.Document(
                    text=retrieval_text,
                    model="Qdrant/bm25",
                ),
            }
        points.append(
            models.PointStruct(
                id=_point_id(document_id, page_number, language, idx),
                vector=point_vector,
                payload=payload,
            )
        )

    try:
        client.upsert(collection_name=collection_name, points=points, wait=True)
        _delete_obsolete_chunks(
            client,
            collection_name,
            document_id,
            page_number,
            len(points),
        )
        logger.info(
            "Upserted %d chunks for document %s page %d into '%s'",
            len(points),
            document_id,
            page_number,
            collection_name,
        )
    except Exception as exc:
        logger.error("Failed to upsert points into '%s': %s", collection_name, exc)
        raise RuntimeError(f"Qdrant upsert failed: {exc}") from exc


def search_embeddings(
    vector: list[float],
    workspace_id: str,
    limit: int = 20,
    query_text: str | None = None,
    collection_name: str = COLLECTION_NAME,
    hybrid: bool = False,
) -> list[dict]:
    """Search one workspace using dense retrieval or dense plus BM25 RRF."""
    if not vector:
        raise ValueError("No vector provided for search")

    client = get_qdrant_client()
    workspace_filter = _workspace_filter(workspace_id)
    try:
        _ensure_workspace_index(client, collection_name)
        if hybrid:
            if not query_text:
                raise ValueError("A query text is required for hybrid search")
            response = client.query_points(
                collection_name=collection_name,
                prefetch=[
                    models.Prefetch(
                        query=vector,
                        using="dense",
                        filter=workspace_filter,
                        limit=limit,
                    ),
                    models.Prefetch(
                        query=models.Document(
                            text=query_text,
                            model="Qdrant/bm25",
                        ),
                        using="bm25",
                        filter=workspace_filter,
                        limit=limit,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=workspace_filter,
                limit=limit,
                with_payload=True,
            )
        else:
            response = client.query_points(
                collection_name=collection_name,
                query=vector,
                query_filter=workspace_filter,
                limit=limit,
                with_payload=True,
            )
    except Exception as exc:
        logger.error("Failed to search collection '%s': %s", collection_name, exc)
        raise RuntimeError(f"Qdrant search failed: {exc}") from exc

    return [
        {
            "id": str(point.id),
            "score": point.score,
            "payload": point.payload or {},
        }
        for point in response.points
    ]
