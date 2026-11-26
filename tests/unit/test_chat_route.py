from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio

from app.api.routes.chat import router
from app.core.database import get_db
from app.services.rag.chat import NoResultsError

WORKSPACE_ID = "22222222-2222-2222-2222-222222222222"


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, workspace):
        self._workspace = workspace

    async def execute(self, stmt):
        return _FakeResult(self._workspace)


def _make_app(workspace=None):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield _FakeSession(workspace)

    app.dependency_overrides[get_db] = override_db
    return app


@pytest_asyncio.fixture
async def chat_client():
    app = _make_app(workspace=MagicMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _payload():
    return {
        "workspace_id": WORKSPACE_ID,
        "message": "¿Qué información contiene el documento?",
    }


@pytest.mark.unit
class TestChatRoute:
    @patch("app.api.routes.chat.search_data")
    async def test_chat_returns_search_results(self, mock_search, chat_client):
        mock_search.return_value = [
            {
                "id": "p1",
                "score": 0.91,
                "payload": {"text": "chunk one", "document_id": "doc-1"},
            }
        ]

        resp = await chat_client.post("/api/v1/chat", json=_payload())

        assert resp.status_code == 200
        data = resp.json()
        assert data["message_received"] is True
        assert data["message"] == _payload()["message"]
        assert data["results"][0]["id"] == "p1"
        assert data["results"][0]["score"] == 0.91

        mock_search.assert_called_once_with(_payload()["message"], WORKSPACE_ID)

    @patch("app.api.routes.chat.search_data")
    async def test_chat_returns_404_when_no_results(self, mock_search, chat_client):
        mock_search.side_effect = NoResultsError("No matching data found")

        resp = await chat_client.post("/api/v1/chat", json=_payload())

        assert resp.status_code == 404
        assert "No matching data found" in resp.json()["detail"]

    @patch("app.api.routes.chat.search_data")
    async def test_chat_returns_503_on_runtime_error(self, mock_search, chat_client):
        mock_search.side_effect = RuntimeError("Qdrant is down")

        resp = await chat_client.post("/api/v1/chat", json=_payload())

        assert resp.status_code == 503
        assert "Qdrant is down" in resp.json()["detail"]

    async def test_chat_404_when_workspace_not_found(self):
        app = _make_app(workspace=None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/v1/chat", json=_payload())

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    async def test_chat_422_when_message_too_short(self, chat_client):
        resp = await chat_client.post(
            "/api/v1/chat", json={"workspace_id": WORKSPACE_ID, "message": "hola"}
        )

        assert resp.status_code == 422

    async def test_chat_422_when_message_whitespace_only(self, chat_client):
        resp = await chat_client.post(
            "/api/v1/chat",
            json={"workspace_id": WORKSPACE_ID, "message": "      "},
        )

        assert resp.status_code == 422

    async def test_chat_422_when_workspace_invalid_uuid(self, chat_client):
        resp = await chat_client.post(
            "/api/v1/chat",
            json={"workspace_id": "not-a-uuid", "message": "una pregunta larga"},
        )

        assert resp.status_code == 422


@pytest.mark.unit
class TestChatRouteRegistration:
    def test_chat_router_registered_in_main_app(self):
        from main import app

        paths = [route.path for route in app.routes]
        assert "/api/v1/chat" in paths
