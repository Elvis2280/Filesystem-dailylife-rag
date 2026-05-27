
import os

from dotenv import load_dotenv

from langchain_ollama import (
    OllamaEmbeddings,
)

load_dotenv()


embeddings = OllamaEmbeddings(
    model=os.getenv(
        "EMBED_MODEL",
        "mxbai-embed-large",
    )
)


def get_embedding_model():
    """
    Return embedding model instance.
    """

    return embeddings