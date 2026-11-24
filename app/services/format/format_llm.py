from app.core.prompts import FORMAT_TO_MARKDOWN_PROMP
from app.services.ai.model_preferences import ModelRole, get_model_name_sync
from app.services.ai.ollama_sync import OllamaSyncClient


def format_markdown(content: str) -> str:
    """
    Format the content from plain text format to markdown format.
    """
    client = OllamaSyncClient()
    return client.generate(
        model=get_model_name_sync(ModelRole.FORMATTING),
        prompt=(FORMAT_TO_MARKDOWN_PROMP + "\n\n" + content),
    )
