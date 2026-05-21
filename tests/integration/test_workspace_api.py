import uuid

import pytest


@pytest.mark.integration
class TestWorkspaceApi:
    @pytest.mark.asyncio
    async def test_create_workspace_returns_201(self, client):
        unique_name = f"Test-{uuid.uuid4().hex[:8]}"
        response = await client.post("/api/v1/workspace", json={"name": unique_name})

        assert response.status_code == 201
        data = response.json()
        assert data["display_name"] == unique_name
        assert data["slug"] == unique_name.lower()
        assert "id" in data
        assert "storage_key" in data
        assert data["status"] == "active"
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_duplicate_workspace_returns_409(self, client):
        unique_name = f"Dup-{uuid.uuid4().hex[:8]}"
        await client.post("/api/v1/workspace", json={"name": unique_name})
        response = await client.post("/api/v1/workspace", json={"name": unique_name})

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_empty_body_returns_422(self, client):
        response = await client.post("/api/v1/workspace", json={})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_name_returns_422(self, client):
        response = await client.post("/api/v1/workspace", json={"name": ""})

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_name_returns_422(self, client):
        response = await client.post("/api/v1/workspace", json={"other": "value"})

        assert response.status_code == 422
