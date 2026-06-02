"""AI service clients for OCR and text generation.

Provides async (OllamaClient) and sync (OllamaSyncClient) wrappers
for the Ollama API. The async client is used by FastAPI health checks,
while the sync client is used by Celery worker tasks for OCR processing.
"""
