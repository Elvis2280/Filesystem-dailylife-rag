"""Business logic layer for the Memory RAG application.

This package contains pure service classes and functions with no
framework dependencies (FastAPI, Celery). Each sub-package handles
a specific domain: AI clients, OCR extraction, chunking, language
detection, metadata management, RAG orchestration, vector retrieval,
and file/workspace storage.

Services are designed to be importable from both synchronous
(Celery workers) and asynchronous (FastAPI) contexts.
"""
