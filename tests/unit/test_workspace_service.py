from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.storage.workspace import (
    create_workspace,
    disable_workspace,
    get_workspaces_tree_json,
    WorkspaceAlreadyDisabledError,
)
from app.core.constant import WorkspaceStatus
from app.models.workspace import WorkspaceModel
from app.models.disabled_workspace import DisabledWorkspace
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
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

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
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with pytest.raises(ValueError, match="already exists"):
            await create_workspace("Test Project", db_session)

    @pytest.mark.asyncio
    async def test_raises_value_error_if_workspace_is_disabled(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        existing = WorkspaceModel(
            display_name="Test Project",
            slug="test-project",
            storage_key="existing-key",
            status=WorkspaceStatus.DISABLED,
        )
        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
        )

        with pytest.raises(ValueError, match="exists but is disabled"):
            await create_workspace("Test Project", db_session)

    @pytest.mark.asyncio
    async def test_raises_value_error_if_workspace_is_active_in_db(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        existing = WorkspaceModel(
            display_name="Test Project",
            slug="test-project",
            storage_key="existing-key",
            status=WorkspaceStatus.ACTIVE,
        )
        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
        )

        with pytest.raises(ValueError, match="already exists"):
            await create_workspace("Test Project", db_session)

    @pytest.mark.asyncio
    async def test_raises_runtime_error_on_db_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
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
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        await create_workspace("My Project", db_session)

        assert (tmp_path / "english" / "my-project").exists()
        assert (tmp_path / "japanese" / "my-project").exists()


@pytest.mark.unit
class TestGetWorkspacesTreeJson:
    @pytest.mark.asyncio
    async def test_returns_grouped_by_language(self):
        w1 = WorkspaceModel(
            display_name="Project A",
            slug="project-a",
            storage_key="key-a",
            status=WorkspaceStatus.ACTIVE,
        )
        w2 = WorkspaceModel(
            display_name="Project B",
            slug="project-b",
            storage_key="key-b",
            status=WorkspaceStatus.ACTIVE,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [w1, w2]

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=mock_result)

        tree = await get_workspaces_tree_json(db_session)

        assert "english" in tree
        assert "japanese" in tree
        assert len(tree["english"]) == 2
        assert tree["english"][0] == {"display_name": "Project A", "slug": "project-a"}
        assert tree["english"][1] == {"display_name": "Project B", "slug": "project-b"}
        assert tree["japanese"] == tree["english"]

    @pytest.mark.asyncio
    async def test_filters_out_disabled_workspaces(self):
        w_active = WorkspaceModel(
            display_name="Active",
            slug="active",
            storage_key="key-active",
            status=WorkspaceStatus.ACTIVE,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [w_active]

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=mock_result)

        tree = await get_workspaces_tree_json(db_session)

        assert len(tree["english"]) == 1
        assert tree["english"][0]["slug"] == "active"


@pytest.mark.unit
class TestDisableWorkspace:
    @pytest.mark.asyncio
    async def test_raises_value_error_if_workspace_not_found(self):
        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with pytest.raises(ValueError, match="Workspace does not exist"):
            await disable_workspace("missing-slug", db_session)

    @pytest.mark.asyncio
    async def test_raises_error_if_already_disabled(self):
        workspace = WorkspaceModel(
            display_name="Test",
            slug="test-slug",
            storage_key="key-123",
            status=WorkspaceStatus.DISABLED,
        )

        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=workspace))
        )

        with pytest.raises(WorkspaceAlreadyDisabledError, match="already disabled"):
            await disable_workspace("test-slug", db_session)

    @pytest.mark.asyncio
    async def test_raises_value_error_if_folders_not_found(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        workspace = WorkspaceModel(
            display_name="Test",
            slug="test-slug",
            storage_key="key-123",
            status=WorkspaceStatus.ACTIVE,
        )

        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=workspace))
        )

        with pytest.raises(ValueError, match="Workspace folders do not exist"):
            await disable_workspace("test-slug", db_session)

    @pytest.mark.asyncio
    async def test_disables_workspace_and_inserts_records(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        (tmp_path / "english" / "test-slug").mkdir(parents=True)
        (tmp_path / "japanese" / "test-slug").mkdir(parents=True)

        workspace = WorkspaceModel(
            display_name="Test",
            slug="test-slug",
            storage_key="key-123",
            status=WorkspaceStatus.ACTIVE,
        )

        active_workspace = WorkspaceModel(
            display_name="Other",
            slug="other",
            storage_key="other-key",
            status=WorkspaceStatus.ACTIVE,
        )

        lookup_result = MagicMock()
        lookup_result.scalar_one_or_none.return_value = workspace

        tree_result = MagicMock()
        tree_result.scalars.return_value.all.return_value = [active_workspace]

        db_session = AsyncMock()
        db_session.commit = AsyncMock()
        db_session.refresh = AsyncMock()
        db_session.execute = AsyncMock(side_effect=[lookup_result, tree_result])
        db_session.add = MagicMock()

        display_name, tree = await disable_workspace("test-slug", db_session)

        assert display_name == "Test"
        assert len(tree["english"]) == 1
        assert workspace.status == WorkspaceStatus.DISABLED
        assert workspace.disabled_at is not None
        assert db_session.add.call_count == 2

        added_models = [call.args[0] for call in db_session.add.call_args_list]
        assert all(isinstance(m, DisabledWorkspace) for m in added_models)
        assert {m.lang for m in added_models} == {"english", "japanese"}
        assert all(m.workspace_storage_key == "key-123" for m in added_models)

    @pytest.mark.asyncio
    async def test_partial_disable_when_one_folder_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        (tmp_path / "english" / "test-slug").mkdir(parents=True)

        workspace = WorkspaceModel(
            display_name="Test",
            slug="test-slug",
            storage_key="key-123",
            status=WorkspaceStatus.ACTIVE,
        )

        active_workspace = WorkspaceModel(
            display_name="Other",
            slug="other",
            storage_key="other-key",
            status=WorkspaceStatus.ACTIVE,
        )

        lookup_result = MagicMock()
        lookup_result.scalar_one_or_none.return_value = workspace

        tree_result = MagicMock()
        tree_result.scalars.return_value.all.return_value = [active_workspace]

        db_session = AsyncMock()
        db_session.commit = AsyncMock()
        db_session.refresh = AsyncMock()
        db_session.execute = AsyncMock(side_effect=[lookup_result, tree_result])
        db_session.add = MagicMock()

        display_name, tree = await disable_workspace("test-slug", db_session)

        assert display_name == "Test"
        added_models = [call.args[0] for call in db_session.add.call_args_list]
        assert len(added_models) == 1
        assert added_models[0].lang == "english"
        assert workspace.status == WorkspaceStatus.DISABLED
        assert workspace.disabled_at is not None

    @pytest.mark.asyncio
    async def test_raises_runtime_error_on_db_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_PATH", str(tmp_path)
        )

        (tmp_path / "english" / "test-slug").mkdir(parents=True)

        workspace = WorkspaceModel(
            display_name="Test",
            slug="test-slug",
            storage_key="key-123",
            status=WorkspaceStatus.ACTIVE,
        )

        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=workspace))
        )
        db_session.commit = AsyncMock(side_effect=SQLAlchemyError("DB error"))
        db_session.add = MagicMock()

        with pytest.raises(RuntimeError, match="Failed to disable workspace"):
            await disable_workspace("test-slug", db_session)

        db_session.rollback.assert_awaited_once()
