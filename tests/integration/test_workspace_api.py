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
        assert data["name"] == unique_name
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
    async def test_disabled_workspace_returns_409(self, client):
        unique_name = f"Dis-{uuid.uuid4().hex[:8]}"
        create_resp = await client.post("/api/v1/workspace", json={"name": unique_name})
        assert create_resp.status_code == 201
        workspace_id = create_resp.json()["id"]

        delete_resp = await client.post(f"/api/v1/workspace/{workspace_id}/disable")
        assert delete_resp.status_code == 200

        response = await client.post("/api/v1/workspace", json={"name": unique_name})

        assert response.status_code == 409
        assert "exists but is disabled" in response.json()["detail"]

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

    @pytest.mark.asyncio
    async def test_get_workspace_tree_returns_200(self, client):
        unique_name = f"Tree-{uuid.uuid4().hex[:8]}"
        await client.post("/api/v1/workspace", json={"name": unique_name})

        response = await client.get("/api/v1/workspace/tree")

        assert response.status_code == 200
        data = response.json()
        assert "workspaces" in data
        assert isinstance(data["workspaces"], list)
        names = [w["name"] for w in data["workspaces"]]
        assert unique_name in names

    @pytest.mark.asyncio
    async def test_disable_workspace_returns_200(self, client):
        unique_name = f"Del-{uuid.uuid4().hex[:8]}"

        create_resp = await client.post("/api/v1/workspace", json={"name": unique_name})
        assert create_resp.status_code == 201
        workspace_id = create_resp.json()["id"]

        response = await client.post(f"/api/v1/workspace/{workspace_id}/disable")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "disabled successfully" in data["message"]

    @pytest.mark.asyncio
    async def test_disable_already_disabled_returns_409(self, client):
        unique_name = f"Dis2-{uuid.uuid4().hex[:8]}"

        create_resp = await client.post("/api/v1/workspace", json={"name": unique_name})
        assert create_resp.status_code == 201
        workspace_id = create_resp.json()["id"]

        await client.post(f"/api/v1/workspace/{workspace_id}/disable")
        response = await client.post(f"/api/v1/workspace/{workspace_id}/disable")

        assert response.status_code == 409
        assert "already disabled" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_disable_nonexistent_workspace_returns_404(self, client):
        response = await client.post(f"/api/v1/workspace/{uuid.uuid4()}/disable")

        assert response.status_code == 404
        assert "not exist" in response.json()["detail"]
