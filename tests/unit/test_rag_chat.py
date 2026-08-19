from unittest.mock import patch

import pytest

from app.services.rag.chat import NoResultsError, search_data


@pytest.mark.unit
class TestSearchData:
    @patch("app.services.rag.chat.search_embeddings")
    @patch("app.services.rag.chat.embedding")
    def test_search_data_embeds_message_and_searches(
        self, mock_embedding, mock_search_embeddings
    ):
        mock_embedding.return_value = [[0.1, 0.2]]
        mock_search_embeddings.return_value = [{"id": "p1", "score": 0.9}]

        results = search_data(
            "una pregunta sobre el documento", "22222222-2222-2222-2222-222222222222"
        )

        mock_embedding.assert_called_once_with(["una pregunta sobre el documento"])
        mock_search_embeddings.assert_called_once_with(
            [0.1, 0.2],
            "22222222-2222-2222-2222-222222222222",
            limit=3,
        )
        assert results == [{"id": "p1", "score": 0.9}]

    @patch("app.services.rag.chat.search_embeddings")
    @patch("app.services.rag.chat.embedding")
    def test_search_data_raises_no_results(
        self, mock_embedding, mock_search_embeddings
    ):
        mock_embedding.return_value = [[0.1, 0.2]]
        mock_search_embeddings.return_value = []

        with pytest.raises(NoResultsError):
            search_data("una pregunta larga", "22222222-2222-2222-2222-222222222222")

    def test_search_data_rejects_empty_message(self):
        with pytest.raises(ValueError, match="not be empty"):
            search_data("", "22222222-2222-2222-2222-222222222222")

    def test_search_data_rejects_whitespace_message(self):
        with pytest.raises(ValueError, match="not be empty"):
            search_data("      ", "22222222-2222-2222-2222-222222222222")

    def test_search_data_rejects_short_message(self):
        with pytest.raises(ValueError, match="at least 6"):
            search_data("hola", "22222222-2222-2222-2222-222222222222")
