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
