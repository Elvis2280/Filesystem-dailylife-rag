from app.core.config import settings
from app.core.prompts import FORMAT_TO_MARKDOWN_PROMP
from app.services.ai.ollama_sync import OllamaSyncClient


def format_markdown(content: str) -> str:
    """
    Format the content from plain text format to markdown format.
    """
    client = OllamaSyncClient()
    return client.generate(
        model=settings.OLLAMA_MODEL_FORMAT,
        prompt=(FORMAT_TO_MARKDOWN_PROMP + "\n\n" + content),
    )
