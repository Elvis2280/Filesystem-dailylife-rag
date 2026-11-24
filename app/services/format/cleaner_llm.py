from app.core.prompts import CLEANING_PROMPT
from app.services.ai.model_preferences import ModelRole, get_model_name_sync
from app.services.ai.ollama_sync import OllamaSyncClient


def clean_text(content: str) -> str:
    """Clean raw OCR text by removing isolated floating numbers/labels.

    Calls the qwen2.5:1.5b model with CLEANING_PROMPT and the input text.
    Returns the cleaned text, or "[NO_SEARCHABLE_CONTENT]" when the input
    contained nothing but useless floating numbers.
    """
    client = OllamaSyncClient()
    return client.generate(
        model=get_model_name_sync(ModelRole.CLEANING),
        prompt=(CLEANING_PROMPT + "\n\n" + content),
    )
