from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
import pytest_asyncio

from app.api.routes.chat import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest_asyncio.fixture
async def chat_client():
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.unit
class TestChatRoute:
    async def test_chat_returns_message_received(self, chat_client):
        resp = await chat_client.post("/api/v1/chat", json={"message": "Hola"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["message_received"] is True
        assert data["message"] == "Hola"

    async def test_chat_echoes_message(self, chat_client):
        resp = await chat_client.post(
            "/api/v1/chat", json={"message": "¿Cuántas páginas tiene este documento?"}
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == "¿Cuántas páginas tiene este documento?"

    async def test_chat_requires_message_field(self, chat_client):
        resp = await chat_client.post("/api/v1/chat", json={})

        assert resp.status_code == 422


@pytest.mark.unit
class TestChatRouteRegistration:
    def test_chat_router_registered_in_main_app(self):
        from main import app

        paths = [route.path for route in app.routes]
        assert "/api/v1/chat" in paths
