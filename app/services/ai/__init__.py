"""AI service clients for Ollama text generation.

Provides async (OllamaClient) and sync (OllamaSyncClient) wrappers
for the Ollama API. Both clients expose generic generate() methods
that accept model, prompt, and image as parameters. Prompt engineering
and model selection are handled by callers (e.g. app.services.ocr).
"""
