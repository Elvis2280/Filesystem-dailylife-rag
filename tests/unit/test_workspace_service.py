from unittest.mock import AsyncMock

import pytest

from app.services.storage.workspace import create_workspace
from app.models.workspace import WorkspaceModel
from sqlalchemy.exc import SQLAlchemyError


@pytest.mark.unit
class TestCreateWorkspace:
    @pytest.mark.asyncio
    async def test_creates_workspace_and_returns_model(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        db_session = AsyncMock()
        db_session.refresh = AsyncMock()

        async def fake_commit():
            pass

        db_session.commit = AsyncMock(side_effect=fake_commit)

        result = await create_workspace("Test Project", db_session)

        assert isinstance(result, WorkspaceModel)
        assert result.display_name == "Test Project"
        assert result.slug == "test-project"
        assert isinstance(result.storage_key, str)
        assert len(result.storage_key) > 0

    @pytest.mark.asyncio
    async def test_raises_value_error_if_workspace_exists(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        slug = "test-project"
        for lang in ["english", "japanese"]:
            (tmp_path / lang / slug).mkdir(parents=True)

        db_session = AsyncMock()

        with pytest.raises(ValueError, match="already exists"):
            await create_workspace("Test Project", db_session)

    @pytest.mark.asyncio
    async def test_raises_runtime_error_on_db_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        db_session = AsyncMock()
        db_session.commit = AsyncMock(side_effect=SQLAlchemyError("DB error"))

        with pytest.raises(RuntimeError, match="Failed to create workspace"):
            await create_workspace("Test Project", db_session)

        db_session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_filesystem_directories(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        db_session = AsyncMock()

        async def fake_commit():
            pass

        db_session.commit = AsyncMock(side_effect=fake_commit)
        db_session.refresh = AsyncMock()

        await create_workspace("My Project", db_session)

        assert (tmp_path / "english" / "my-project").exists()
        assert (tmp_path / "japanese" / "my-project").exists()
