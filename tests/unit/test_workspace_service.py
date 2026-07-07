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
import uuid


@pytest.mark.unit
class TestCreateWorkspace:
    @pytest.mark.asyncio
    async def test_creates_workspace_and_returns_model(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_WORKSPACES_PATH",
            str(tmp_path),
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
        assert result.name == "Test Project"
        assert result.slug == "test-project"
        assert isinstance(result.storage_key, str)
        assert len(result.storage_key) > 0

    @pytest.mark.asyncio
    async def test_raises_value_error_if_workspace_exists(self, monkeypatch, tmp_path):
        ws_id = uuid.uuid4()
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_WORKSPACES_PATH",
            str(tmp_path),
        )
        monkeypatch.setattr(
            "app.services.storage.workspace.uuid.uuid4",
            lambda: ws_id,
        )

        (tmp_path / str(ws_id)).mkdir(parents=True)

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
            "app.services.storage.workspace.settings.BRAIN_WORKSPACES_PATH",
            str(tmp_path),
        )

        existing = WorkspaceModel(
            name="Test Project",
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
            "app.services.storage.workspace.settings.BRAIN_WORKSPACES_PATH",
            str(tmp_path),
        )

        existing = WorkspaceModel(
            name="Test Project",
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
            "app.services.storage.workspace.settings.BRAIN_WORKSPACES_PATH",
            str(tmp_path),
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
            "app.services.storage.workspace.settings.BRAIN_WORKSPACES_PATH",
            str(tmp_path),
        )

        db_session = AsyncMock()

        async def fake_commit():
            pass

        db_session.commit = AsyncMock(side_effect=fake_commit)
        db_session.refresh = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        result = await create_workspace("My Project", db_session)

        ws_dir = tmp_path / str(result.id)
        assert ws_dir.exists()
        assert (ws_dir / "files").exists()
        assert (ws_dir / "translation" / "english").exists()
        assert (ws_dir / "translation" / "japanese").exists()


@pytest.mark.unit
class TestGetWorkspacesTreeJson:
    @pytest.mark.asyncio
    async def test_returns_workspaces_with_nested_children(self):
        ws_id_1 = uuid.uuid4()
        ws_id_2 = uuid.uuid4()

        w1 = WorkspaceModel(
            id=ws_id_1,
            name="Project A",
            slug="project-a",
            storage_key="key-a",
            status=WorkspaceStatus.ACTIVE,
        )
        w2 = WorkspaceModel(
            id=ws_id_2,
            name="Project B",
            slug="project-b",
            storage_key="key-b",
            status=WorkspaceStatus.ACTIVE,
        )

        # Mock documents for workspace 1
        doc1 = MagicMock()
        doc1.id = uuid.uuid4()
        doc1.original_filename = "resume.pdf"
        doc1.language = "en"
        doc1.status = "ocr_completed"

        doc2 = MagicMock()
        doc2.id = uuid.uuid4()
        doc2.original_filename = "invoice.pdf"
        doc2.language = "ja"
        doc2.status = "in_storage"

        # No documents for workspace 2
        mock_workspace_result = MagicMock()
        mock_workspace_result.scalars.return_value.all.return_value = [w1, w2]

        mock_docs_result_1 = MagicMock()
        mock_docs_result_1.scalars.return_value.all.return_value = [doc1, doc2]

        mock_docs_result_2 = MagicMock()
        mock_docs_result_2.scalars.return_value.all.return_value = []

        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            side_effect=[
                mock_workspace_result,
                mock_docs_result_1,
                mock_docs_result_2,
            ]
        )

        tree = await get_workspaces_tree_json(db_session)

        assert len(tree) == 2

        ws1 = tree[0]
        assert ws1["id"] == str(ws_id_1)
        assert ws1["name"] == "Project A"
        assert ws1["status"] == "active"
        assert len(ws1["children"]) == 2

        files_folder = ws1["children"][0]
        assert files_folder["type"] == "folder"
        assert files_folder["name"] == "Files"
        assert files_folder["path"] == "files"
        assert len(files_folder["children"]) == 2
        assert files_folder["children"][0]["type"] == "file"
        assert files_folder["children"][0]["name"] == "resume.pdf"
        assert files_folder["children"][0]["language"] == "en"
        assert files_folder["children"][0]["status"] == "ocr_completed"
        assert files_folder["children"][1]["type"] == "file"
        assert files_folder["children"][1]["name"] == "invoice.pdf"
        assert files_folder["children"][1]["language"] == "ja"
        assert files_folder["children"][1]["status"] == "in_storage"

        translation_folder = ws1["children"][1]
        assert translation_folder["name"] == "Translation"
        assert translation_folder["path"] == "translation"
        assert len(translation_folder["children"]) == 2
        assert translation_folder["children"][0]["name"] == "English"
        assert translation_folder["children"][0]["path"] == "translation/english"
        assert translation_folder["children"][0]["children"] == []
        assert translation_folder["children"][1]["name"] == "Japanese"
        assert translation_folder["children"][1]["path"] == "translation/japanese"
        assert translation_folder["children"][1]["children"] == []

        ws2 = tree[1]
        assert ws2["id"] == str(ws_id_2)
        assert ws2["name"] == "Project B"
        files_folder_2 = ws2["children"][0]
        assert files_folder_2["children"] == []

    @pytest.mark.asyncio
    async def test_tree_id_is_workspace_uuid(self):
        ws_id = uuid.uuid4()
        workspace = WorkspaceModel(
            id=ws_id,
            name="Test",
            slug="test",
            storage_key="key",
            status=WorkspaceStatus.ACTIVE,
        )

        mock_ws_result = MagicMock()
        mock_ws_result.scalars.return_value.all.return_value = [workspace]

        mock_docs_result = MagicMock()
        mock_docs_result.scalars.return_value.all.return_value = []

        db_session = AsyncMock()
        db_session.execute = AsyncMock(side_effect=[mock_ws_result, mock_docs_result])

        tree = await get_workspaces_tree_json(db_session)

        assert len(tree) == 1
        assert tree[0]["id"] == str(ws_id)
        assert len(tree[0]["id"]) > 0

    @pytest.mark.asyncio
    async def test_excludes_disabled_workspaces(self):
        w_active = WorkspaceModel(
            id=uuid.uuid4(),
            name="Active",
            slug="active",
            storage_key="key-active",
            status=WorkspaceStatus.ACTIVE,
        )
        # Only active workspace is returned by the mock
        mock_workspace_result = MagicMock()
        mock_workspace_result.scalars.return_value.all.return_value = [w_active]

        mock_docs_result = MagicMock()
        mock_docs_result.scalars.return_value.all.return_value = []

        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            side_effect=[mock_workspace_result, mock_docs_result]
        )

        tree = await get_workspaces_tree_json(db_session)

        assert len(tree) == 1
        assert tree[0]["name"] == "Active"


@pytest.mark.unit
class TestDisableWorkspace:
    @pytest.mark.asyncio
    async def test_raises_value_error_if_workspace_not_found(self):
        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with pytest.raises(ValueError, match="Workspace does not exist"):
            await disable_workspace("00000000-0000-0000-0000-000000000001", db_session)

    @pytest.mark.asyncio
    async def test_raises_error_if_already_disabled(self):
        workspace = WorkspaceModel(
            name="Test",
            slug="test-slug",
            storage_key="key-123",
            status=WorkspaceStatus.DISABLED,
        )

        db_session = AsyncMock()
        db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=workspace))
        )

        with pytest.raises(WorkspaceAlreadyDisabledError, match="already disabled"):
            await disable_workspace("00000000-0000-0000-0000-000000000001", db_session)

    @pytest.mark.asyncio
    async def test_disables_workspace_and_inserts_record(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_WORKSPACES_PATH",
            str(tmp_path),
        )

        ws_id = uuid.uuid4()
        (tmp_path / str(ws_id) / "files").mkdir(parents=True)

        workspace = WorkspaceModel(
            id=ws_id,
            name="Test",
            slug="test-slug",
            storage_key="key-123",
            status=WorkspaceStatus.ACTIVE,
        )

        lookup_result = MagicMock()
        lookup_result.scalar_one_or_none.return_value = workspace

        db_session = AsyncMock()
        db_session.commit = AsyncMock()
        db_session.refresh = AsyncMock()
        db_session.execute = AsyncMock(side_effect=[lookup_result])
        db_session.add = MagicMock()

        name = await disable_workspace(str(ws_id), db_session)

        assert name == "Test"
        assert workspace.status == WorkspaceStatus.DISABLED
        assert workspace.disabled_at is not None
        assert db_session.add.call_count == 1

        added_model = db_session.add.call_args[0][0]
        assert isinstance(added_model, DisabledWorkspace)
        assert added_model.lang == "all"
        assert added_model.workspace_storage_key == "key-123"

    @pytest.mark.asyncio
    async def test_raises_runtime_error_on_db_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "app.services.storage.workspace.settings.BRAIN_WORKSPACES_PATH",
            str(tmp_path),
        )

        ws_id = uuid.uuid4()
        (tmp_path / str(ws_id) / "files").mkdir(parents=True)

        workspace = WorkspaceModel(
            id=ws_id,
            name="Test",
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
            await disable_workspace(str(ws_id), db_session)

        db_session.rollback.assert_awaited_once()
