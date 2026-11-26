"""Destructively reset the project-owned database and object artifacts.

This command intentionally leaves Redis and all Qdrant collections except the
document embeddings collection untouched. The Garage bucket is preserved but
all objects inside it are removed.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from alembic import command
from alembic.config import Config
from qdrant_client import QdrantClient
from sqlalchemy import text

from app.core.config import settings
from app.core.database import sync_engine
from app.services.rag.qdrant_client import COLLECTION_NAME
from app.services.storage.object_storage import delete_prefix


def _validated_cleanup_root(path_value: str, label: str) -> Path:
    path = Path(path_value).resolve()
    project_root = Path.cwd().resolve()
    forbidden = {Path("/"), Path.home().resolve(), project_root}
    if path in forbidden or not path.is_relative_to(project_root):
        raise RuntimeError(f"Refusing to clean unsafe {label} path: {path}")
    return path


def _clear_directory_contents(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _reset_postgres() -> None:
    with sync_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    alembic_config = Config(str(Path(__file__).with_name("alembic.ini")))
    command.upgrade(alembic_config, "head")


def _reset_qdrant() -> None:
    client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)


def _reset_object_storage() -> int:
    return delete_prefix()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-clean-reset",
        action="store_true",
        help="Confirm permanent deletion of project PostgreSQL and file data.",
    )
    args = parser.parse_args()
    if not args.confirm_clean_reset:
        parser.error("pass --confirm-clean-reset to perform the destructive reset")

    cleanup_roots = [
        _validated_cleanup_root(settings.TEMP_PATH, "temporary storage"),
    ]
    for path in cleanup_roots:
        _clear_directory_contents(path)
    deleted_objects = _reset_object_storage()
    _reset_postgres()
    _reset_qdrant()
    print(
        "Project PostgreSQL, Garage objects, local scratch files, and the documents "
        f"Qdrant collection were reset ({deleted_objects} Garage objects deleted)."
    )


if __name__ == "__main__":
    main()
