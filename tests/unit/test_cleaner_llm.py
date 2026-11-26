from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.prompts import CLEANING_PROMPT


@pytest.mark.unit
class TestCleanerLlm:
    def test_clean_text_calls_ollama_with_cleaner_model_and_prompt(self):
        from app.services.format.cleaner_llm import clean_text

        with patch(
            "app.services.format.cleaner_llm.OllamaSyncClient"
        ) as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.generate.return_value = "cleaned result"

            result = clean_text("some raw OCR text")

        assert result == "cleaned result"
        mock_client.generate.assert_called_once()
        call_kwargs = mock_client.generate.call_args.kwargs
        assert call_kwargs["model"] == settings.OLLAMA_MODEL_CLEANER
        assert CLEANING_PROMPT in call_kwargs["prompt"]
        assert "some raw OCR text" in call_kwargs["prompt"]

    def test_clean_text_returns_ollama_response(self):
        from app.services.format.cleaner_llm import clean_text

        with patch(
            "app.services.format.cleaner_llm.OllamaSyncClient"
        ) as mock_client_cls:
            mock_client_cls.return_value.generate.return_value = (
                "[NO_SEARCHABLE_CONTENT]"
            )

            result = clean_text("14.5 R7 30")

        assert result == "[NO_SEARCHABLE_CONTENT]"

    def test_clean_text_propagates_runtime_error(self):
        from app.services.format.cleaner_llm import clean_text

        with patch(
            "app.services.format.cleaner_llm.OllamaSyncClient"
        ) as mock_client_cls:
            mock_client_cls.return_value.generate.side_effect = RuntimeError("boom")

            with pytest.raises(RuntimeError, match="boom"):
                clean_text("some text")
