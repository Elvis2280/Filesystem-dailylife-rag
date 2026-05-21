from app.core.utility import error_response, generate_slug, success_response


class TestGenerateSlug:
    def test_lowercase_conversion(self):
        assert generate_slug("My Workspace") == "my-workspace"

    def test_special_characters_removed(self):
        assert generate_slug("Hello!!! World???") == "hello-world"

    def test_leading_trailing_hyphens_removed(self):
        assert generate_slug("---test---") == "test"

    def test_multiple_spaces_collapsed(self):
        assert generate_slug("a   b\tc") == "a-b-c"

    def test_empty_string(self):
        assert generate_slug("") == ""

    def test_only_special_chars(self):
        assert generate_slug("!@#$%") == ""

    def test_numbers_preserved(self):
        assert generate_slug("project 2026") == "project-2026"


class TestSuccessResponse:
    def test_basic_success(self):
        result = success_response(data={"id": 1})
        assert result["status"] == "success"
        assert result["code"] == 200
        assert result["data"] == {"id": 1}
        assert result["message"] is None

    def test_with_message(self):
        result = success_response(data={"key": "val"}, message="Created")
        assert result["message"] == "Created"

    def test_custom_status_code(self):
        result = success_response(data={}, status_code=201)
        assert result["code"] == 201


class TestErrorResponse:
    def test_basic_error(self):
        result = error_response(message="Not found")
        assert result["error"]["status"] == "error"
        assert result["error"]["code"] == 400
        assert result["error"]["message"] == "Not found"
        assert result["error"]["details"] == {}

    def test_with_details(self):
        result = error_response(message="Validation failed", details={"field": "name"})
        assert result["error"]["details"] == {"field": "name"}

    def test_custom_status_code(self):
        result = error_response(message="Conflict", status_code=409)
        assert result["error"]["code"] == 409
