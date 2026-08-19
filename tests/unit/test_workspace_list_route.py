import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.routes.workspace import router
from app.core.database import get_db
from app.models.workspace import WorkspaceModel


class _FakeScalars:
    def __init__(self, workspaces):
        self._workspaces = workspaces

    def all(self):
        return self._workspaces


class _FakeResult:
    def __init__(self, workspaces):
        self._workspaces = workspaces

    def scalars(self):
        return _FakeScalars(self._workspaces)


class _FakeSession:
    def __init__(self, workspaces):
        self._workspaces = workspaces

    async def execute(self, stmt):
        return _FakeResult(self._workspaces)


def _make_app(workspaces):
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield _FakeSession(workspaces)

    app.dependency_overrides[get_db] = override_db
    return app


def _make_workspace(name):
    workspace = WorkspaceModel(name=name, slug=name.lower(), storage_key=f"key-{name}")
    workspace.id = uuid.uuid4()
    workspace.status = "active"
    workspace.created_at = datetime.now(timezone.utc)
    workspace.updated_at = datetime.now(timezone.utc)
    return workspace


@pytest.mark.unit
class TestWorkspaceListRoute:
    async def test_list_returns_all_workspaces(self):
        ws_a = _make_workspace("Alpha")
        ws_b = _make_workspace("Beta")
        app = _make_app([ws_a, ws_b])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/workspace/list")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

        assert data[0]["name"] == "Alpha"
        assert data[0]["id"] == str(ws_a.id)
        assert data[0]["status"] == "active"
        assert "children" not in data[0]

    async def test_list_returns_empty_list_when_no_workspaces(self):
        app = _make_app([])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/workspace/list")

        assert resp.status_code == 200
        assert resp.json() == []

    async def test_tree_route_still_registered(self):
        from main import app

        paths = [route.path for route in app.routes]
        assert "/api/v1/workspace/tree" in paths
        assert "/api/v1/workspace/list" in paths
