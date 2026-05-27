from vectordb.faiss_store import (
    load_vector_db,
    create_vector_db,
    save_vector_db,
)


def document_exists(
    db,
    file_hash: str,
) -> bool:
    """
    Prevent duplicate ingestion.
    """

    if db is None:
        return False

    existing_hashes = set()

    for _, doc in db.docstore._dict.items():

        existing_hashes.add(
            doc.metadata.get("hash")
        )

    return file_hash in existing_hashes


def store_documents(
    docs,
    embeddings,
):
    """
    Store chunks in FAISS.
    """

    db = load_vector_db(
        embeddings
    )

    if db is None:

        db = create_vector_db(
            docs,
            embeddings,
        )

    else:

        db.add_documents(docs)

    save_vector_db(db)