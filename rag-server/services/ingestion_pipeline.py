from services.chunking_service import (
    create_document,
    chunk_document,
)

from services.embedding_service import (
    get_embedding_model,
)

from services.vector_store_service import (
    document_exists,
    store_documents,
)


def ingest_document(
    text,
    source_file,
    file_hash,
    page_number,
):
    """
    Full ingestion pipeline.

    Extracted Text
        ↓
    Document Creation
        ↓
    Chunking
        ↓
    Embedding
        ↓
    Vector Storage
    """

    # STEP 1 — CREATE DOCUMENT
    document = create_document(
        text=text,
        source_file=source_file,
        file_hash=file_hash,
        page_number=page_number,
    )

    # STEP 2 — CHUNK
    docs = chunk_document(
        document
    )

    # STEP 3 — EMBEDDING MODEL
    embeddings = get_embedding_model()

    # STEP 4 — DUPLICATE CHECK
    from vectordb.faiss_store import (
        load_vector_db,
    )

    db = load_vector_db(
        embeddings
    )

    if document_exists(
        db,
        file_hash,
    ):
        print(
            f"{source_file} "
            f"page {page_number} "
            f"already indexed."
        )
        return

    # STEP 5 — STORE
    store_documents(
        docs=docs,
        embeddings=embeddings,
    )

    print(
        f"Ingested page "
        f"{page_number} "
        f"({len(docs)} chunks)"
    )