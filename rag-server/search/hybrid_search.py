# search/hybrid_search.py

import os

from dotenv import load_dotenv

from langchain_community.vectorstores import (
    FAISS,
)

from services.embedding_service import (
    get_embedding_model,
)

from search.bm25_search import (
    bm25_search,
)

from search.semantic_search import (
    semantic_search,
)

load_dotenv()

BASE_DIR = os.path.dirname(__file__)

DB_PATH = os.path.abspath(
    os.path.join(
        BASE_DIR,
        "..",
        os.getenv(
            "DB_PATH",
            "vector_store",
        ),
    )
)


def load_db():
    """
    Load FAISS database.
    """

    embeddings = get_embedding_model()

    return FAISS.load_local(
        DB_PATH,
        embeddings,
        allow_dangerous_deserialization=True,
    )


def hybrid_search(query, top_k=5):
    """
    Hybrid retrieval pipeline.

    1. BM25 Search
    2. Fallback Semantic Search
    """

    db = load_db()

    print("\nUsing BM25 search...")

    bm25_results = bm25_search(
        query=query,
        db=db,
        k=top_k,
    )

    if bm25_results:

        print(
            f"BM25 returned "
            f"{len(bm25_results)} results"
        )

        return bm25_results

    print("No BM25 matches found.")

    print(
        "Falling back to semantic search..."
    )

    semantic_results = semantic_search(
        query=query,
        db=db,
        k=top_k,
    )

    print(
        f"Semantic search returned "
        f"{len(semantic_results)} results"
    )

    return semantic_results