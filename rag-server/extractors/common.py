
import hashlib
import logging

from pathlib import Path

CACHE_DIR = Path.home() / ".openclaw" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# LOGGING SETUP
log_dir = Path.home() / ".openclaw" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

log_file = log_dir / "extract_data.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("extract_file")


def hash_file(file_path: Path) -> str:
    hasher = hashlib.md5()

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)

    return hasher.hexdigest()


def resolve_file_path(path: str) -> Path:
    workspace = Path.home() / ".openclaw" / "workspace"

    file_path = Path(
        str(path).replace(str(workspace), "", 1)
    ).expanduser().resolve()

    if file_path.exists():
        return file_path

    fallback_paths = [
        workspace / file_path.name,
        workspace / "documents" / file_path.name,
    ]

    for candidate in fallback_paths:
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError(f"File not found: {path}")