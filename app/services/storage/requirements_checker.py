import socket
from pathlib import Path

from app.core.config import settings


def ensure_directories() -> dict:
    """Create missing directories. Return status + paths dict."""
    created = []
    for dir_path in settings.REQUIRED_DIRS:
        path = Path(dir_path)
        if path.exists():
            continue
        try:
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))
        except (OSError, PermissionError) as e:
            raise RuntimeError(f"Failed to create directory {dir_path}: {e}") from e

    return {
        "status": "created" if created else "satisfied",
        "paths": created,
    }


def check_service(host: str, port: int, timeout: int = 5) -> bool:
    """Check if a TCP service is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def validate_all() -> dict:
    """Run all checks. Return report dict with created dirs and service status."""
    report = {
        "directories_created": ensure_directories(),
        "services_status": {
            f"{host}:{port}": check_service(host, port)
            for host, port in settings.REQUIRED_SERVICES
        },
    }
    return report
