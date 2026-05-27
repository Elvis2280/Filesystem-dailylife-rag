import os

from dotenv import load_dotenv

from langchain_community.vectorstores import (
    FAISS,
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


def load_vector_db(
    embeddings,
):
    """
    Load existing FAISS DB.
    """

    index_file = os.path.join(
        DB_PATH,
        "index.faiss",
    )

    if not os.path.exists(index_file):
        return None

    return FAISS.load_local(
        DB_PATH,
        embeddings,
        allow_dangerous_deserialization=True,
    )


def create_vector_db(
    docs,
    embeddings,
):
    """
    Create new FAISS DB.
    """

    return FAISS.from_documents(
        docs,
        embeddings,
    )


def save_vector_db(db):
    """
    Save FAISS DB locally.
    """

    db.save_local(DB_PATH)