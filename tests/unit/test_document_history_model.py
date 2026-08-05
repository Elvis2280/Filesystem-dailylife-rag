import pytest

from app.models.document_history import DocumentHistoryModel


@pytest.mark.unit
class TestDocumentHistoryModel:
    def test_tablename(self):
        assert DocumentHistoryModel.__tablename__ == "document_history"

    def test_expected_columns_exist(self):
        column_names = {c.name for c in DocumentHistoryModel.__table__.columns}
        expected = {
            "id",
            "document_id",
            "status",
            "stage",
            "step",
            "message",
            "page_number",
            "total_pages",
            "created_at",
        }
        assert expected.issubset(column_names)

    def test_foreign_key_to_documents(self):
        fks = DocumentHistoryModel.__table__.foreign_keys
        assert len(fks) == 1
        fk = list(fks)[0]
        assert fk.column.table.name == "documents"
        assert fk.parent.name == "document_id"
