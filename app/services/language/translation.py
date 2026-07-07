"""Translation service using Ollama LLM (sync, for Celery workers).

Translates text between English and Japanese using the qwen3:14b model.
Called by the Celery pipeline after language detection to produce
bilingual document copies.
"""

from app.core.config import settings
from app.core.constant import LanguageOptions
from app.core.prompts import TRANSLATE_TO_ENGLISH_PROMPT, TRANSLATE_TO_JAPANESE_PROMPT
from app.services.ai.ollama_sync import OllamaSyncClient

_PROMPTS = {
    LanguageOptions.ENGLISH: TRANSLATE_TO_ENGLISH_PROMPT,
    LanguageOptions.JAPANESE: TRANSLATE_TO_JAPANESE_PROMPT,
}


def translate_content(content: str, lang: LanguageOptions) -> str:
    """Translate text content to the target language.

    Sync function intended for use in Celery worker tasks. Uses the
    configured translation model (OLLAMA_MODEL_TRANSLATION) and a
    language-specific prompt.

    Args:
        content: The text content to translate.
        lang: Target language (ENGLISH or JAPANESE).

    Returns:
        Translated text.

    Raises:
        ValueError: If lang is MIXED or otherwise unsupported.
        RuntimeError: If the Ollama model times out or returns an error.
    """
    if lang == LanguageOptions.MIXED:
        raise ValueError("Cannot translate to MIXED language target")

    prompt_template = _PROMPTS.get(lang)
    if prompt_template is None:
        raise ValueError(f"Unsupported translation target language: {lang}")

    prompt = prompt_template.format(text=content)

    client = OllamaSyncClient()
    try:
        return client.generate(
            model=settings.OLLAMA_MODEL_TRANSLATION,
            prompt=prompt,
        )
    except RuntimeError as e:
        raise RuntimeError(f"Translation to {lang} failed: {e}") from e
