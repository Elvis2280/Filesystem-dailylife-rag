from enum import Enum

# Workspace configuration constants
WORKSPACE_BASE_PATH = "./brain"


# Workspace
class WorkspaceLanguage(str, Enum):
    ENGLISH = "english"
    JAPANESE = "japanese"


class WorkspaceStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class FileStatus(str, Enum):
    STORAGED = "in_storage"


# ── PDF ──────────────────────────────────────────────────────────────
ALLOWED_PDF_EXTENSIONS: set[str] = {".pdf"}
ALLOWED_PDF_MIME_TYPES: set[str] = {"application/pdf"}

# ── Microsoft Office ─────────────────────────────────────────────────
ALLOWED_MS_OFFICE_EXTENSIONS: set[str] = {
    ".doc",
    ".docx",  # Word
    ".xls",
    ".xlsx",  # Excel
    ".ppt",
    ".pptx",  # PowerPoint
}
ALLOWED_MS_OFFICE_MIME_TYPES: set[str] = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# ── Google Office (OpenDocument + CSV exports) ───────────────────────
ALLOWED_GOOGLE_OFFICE_EXTENSIONS: set[str] = {
    ".odt",
    ".ods",
    ".odp",  # OpenDocument
    ".csv",  # Sheets CSV export
}
ALLOWED_GOOGLE_OFFICE_MIME_TYPES: set[str] = {
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "text/csv",
}

# ── Images (for OCR sandbox) ─────────────────────────────────────────
ALLOWED_IMAGE_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_IMAGE_MIME_TYPES: set[str] = {"image/png", "image/jpeg", "image/webp"}

# ── Combined document sets (PDF + Office + Google, excludes images) ──
ALLOWED_DOCUMENT_EXTENSIONS: set[str] = (
    ALLOWED_PDF_EXTENSIONS
    | ALLOWED_MS_OFFICE_EXTENSIONS
    | ALLOWED_GOOGLE_OFFICE_EXTENSIONS
)
ALLOWED_DOCUMENT_MIME_TYPES: set[str] = (
    ALLOWED_PDF_MIME_TYPES
    | ALLOWED_MS_OFFICE_MIME_TYPES
    | ALLOWED_GOOGLE_OFFICE_MIME_TYPES
)
