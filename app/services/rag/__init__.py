"""RAG (Retrieval-Augmented Generation) orchestration service.

Coordinates the end-to-end document processing pipeline: ingestion,
chunking, embedding, indexing, and retrieval. Acts as the bridge
between the storage layers (Redis, Qdrant, Postgres) and the AI
backends (Ollama).
"""
