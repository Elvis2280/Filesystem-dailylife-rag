import socket
from pathlib import Path

from app.core.config import settings


def ensure_directories() -> dict:
    """Validate required directories exist. Return status + missing paths."""
    missing = []
    for dir_path in settings.REQUIRED_DIRS:
        path = Path(dir_path)
        if not path.exists():
            missing.append(str(path))

    return {
        "status": "satisfied" if not missing else "missing",
        "paths": missing,
    }


def ensure_workspace_dirs(workspace_id: str) -> list[str]:
    """Create per-workspace subdirectories on disk. Return list of created paths."""
    created = []
    for subdir in settings.BRAIN_WORKSPACE_SUBDIRS:
        path = Path(settings.workspace_subdir(workspace_id, subdir))
        if not path.exists():
            path.mkdir(parents=True)
            created.append(str(path))
    return created


def check_service(host: str, port: int, timeout: int = 5) -> bool:
    """Check if a TCP service is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


async def check_postgres_db() -> bool:
    """Check actual PG connectivity (not just TCP). Returns True if DB is reachable."""
    import asyncpg

    try:
        conn = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
            timeout=5,
        )
        await conn.close()
        return True
    except Exception:
        return False


async def validate_all() -> dict:
    """Run all checks. Return report dict with created dirs and service status."""
    report = {
        "directories_created": ensure_directories(),
        "services_status": {
            f"{host}:{port}": check_service(host, port)
            for host, port in settings.REQUIRED_SERVICES
        },
        "postgres_db": await check_postgres_db(),
    }
    return report
