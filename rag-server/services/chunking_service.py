
import os

from dotenv import load_dotenv

from langchain_core.documents import (
    Document,
)

from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
)

load_dotenv()


def clean_text(text: str) -> str:
    """
    Normalize extracted text.
    """

    return (
        text.replace("\n", " ")
        .replace("  ", " ")
        .strip()
    )


def create_document(
    text: str,
    source_file: str,
    file_hash: str,
    page_number: int,
) -> Document:
    """
    Create LangChain document object.
    """

    return Document(
        page_content=clean_text(text),
        metadata={
            "source": source_file,
            "hash": file_hash,
            "page": page_number,
        },
    )


def chunk_document(
    document: Document,
) -> list[Document]:
    """
    Split document into chunks.
    """

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=int(
            os.getenv(
                "CHUNK_SIZE",
                300,
            )
        ),
        chunk_overlap=int(
            os.getenv(
                "CHUNK_OVERLAP",
                80,
            )
        ),
    )

    return splitter.split_documents(
        [document]
    )