"""Shared PostgreSQL advisory lock keys for document processing."""

from uuid import UUID


def document_lock_key(document_id: UUID) -> int:
    """Map a document UUID to a stable signed 64-bit advisory lock key."""
    return int.from_bytes(document_id.bytes[:8], byteorder="big", signed=True)
