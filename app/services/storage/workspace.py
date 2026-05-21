import os 
from pathlib import Path
from app.core.constant import WORKSPACE_BASE_PATH, WORKSPACE_LANGUAGES

def create_workspace(workspace_name: str) -> Path:
    """Create a new workspace directory and return its path."""
    base_dir = Path(WORKSPACE_BASE_PATH)
    
    for lang in WORKSPACE_LANGUAGES:
        workspace_dir = base_dir / lang / workspace_name
        try:
            workspace_dir.mkdir(parents=True, exist_ok=False)
            print(f"Workspace created at: {workspace_dir}")
        except FileExistsError:
            print(f"Workspace already exists at: {workspace_dir}")
        except OSError as e:
            raise RuntimeError(f"Failed to create workspace {workspace_dir}: {e}") from e
    return workspace_dir