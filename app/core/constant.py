from enum import Enum

# --- Workspace Configuration ---

WORKSPACE_BASE_PATH = "./brain"


class WorkspaceStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class FileStatus(str, Enum):
    FILE_UPLOADED = "file_uploaded"
    FILE_CONVERSION_STARTED = "file_conversion_started"
    FILE_CONVERSION_FINISHED = "file_conversion_finished"
    OCR_STARTED = "ocr_started"
    OCR_FINISHED = "ocr_finished"
    TRANSLATION_AND_FORMATTING_STARTED = "translation_and_formatting_started"
    TRANSLATION_AND_FORMATTING_FINISHED = "translation_and_formatting_finished"
    FILE_PROCESS_FINISHED = "file_process_finished"
    COMPLETED = "completed"
    FAILED = "failed"


# --- File Pipeline Stages ---

PIPELINE_STEP_TOTAL = 12


class FilePipelineStage(str, Enum):
    PENDING = "pending"
    PDF_CONVERSION = "pdf_conversion"
    IMAGE_CONVERSION = "image_conversion"
    OCR_PROCESSING = "ocr_processing"
    LANGUAGE_DETECTION = "language_detection"
    TRANSLATION = "translation"
    CREATING_MARKDOWN_FILES = "creating_markdown_files"
    FILE_PROCESS_FINISHED = "file_process_finished"
    VERIFY_FILES = "verify_files"
    COLLECTING_DATA = "collecting_data"
    PREPARING_DATA = "preparing_data"
    SAVING_DATA = "saving_data"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def step_number(self) -> int:
        _steps = {
            "pending": 0,
            "pdf_conversion": 1,
            "image_conversion": 2,
            "ocr_processing": 3,
            "language_detection": 4,
            "translation": 5,
            "creating_markdown_files": 6,
            "file_process_finished": 7,
            "verify_files": 8,
            "collecting_data": 9,
            "preparing_data": 10,
            "saving_data": 11,
            "completed": 12,
            "failed": 0,
        }
        return _steps[self.value]

    @property
    def step(self) -> str:
        """Return the legacy fraction stored in document history."""
        return f"{self.step_number}/{PIPELINE_STEP_TOTAL}"

    @property
    def step_total(self) -> int:
        """Return the total number of pipeline steps exposed to clients."""
        return PIPELINE_STEP_TOTAL

    @property
    def message(self) -> str:
        _messages = {
            "pending": "Waiting for task to start...",
            "pdf_conversion": "Converting document to PDF...",
            "image_conversion": "Converting PDF to images...",
            "ocr_processing": "Running OCR...",
            "language_detection": "Detecting language...",
            "translation": "Translating content...",
            "creating_markdown_files": "Creating Markdown files...",
            "file_process_finished": "File processing finished. Starting vector indexing...",
            "verify_files": "Verifying required files...",
            "collecting_data": "Collecting data on page...",
            "preparing_data": "Preparing data on page...",
            "saving_data": "Saving data to vector store...",
            "completed": "Processing completed successfully!",
            "failed": "Processing failed.",
        }
        return _messages[self.value]


# --- Allowed File Types + Extensions ---

# -- PDF --
ALLOWED_PDF_EXTENSIONS: set[str] = {".pdf"}
ALLOWED_PDF_MIME_TYPES: set[str] = {"application/pdf"}

# -- Microsoft Office --
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

# -- Google Office (OpenDocument + CSV exports) --
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

# -- Images (for OCR sandbox) --
ALLOWED_IMAGE_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_IMAGE_MIME_TYPES: set[str] = {"image/png", "image/jpeg", "image/webp"}

# -- Combined document sets (PDF + Office + Google, excludes images) --
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

# -- All uploadable types (documents + images) --
ALLOWED_UPLOAD_MIME_TYPES: set[str] = (
    ALLOWED_DOCUMENT_MIME_TYPES | ALLOWED_IMAGE_MIME_TYPES
)


# -- Language Detection Types --
class LanguageOptions(str, Enum):
    ENGLISH = "EN"
    JAPANESE = "JP"
    MIXED = "MIXED"


class DocumentsType(str, Enum):
    ORIGINAL_FILE = "ORIGINAL"
    CONVERTED_PDF = "CONVERT_PDF"
    IMAGES_PAGES = "IMAGES_PAGES"
    MD_ORIGINAL = "MD_ORIGINAL"
    MD_TRANSLATED = "MD_TRANSLATED"
