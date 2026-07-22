import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Development flag
    IS_DEVELOPMENT: bool = Field(default=False)

    # App
    APP_NAME: str = "Personal Memory RAG"
    DEBUG: bool = False

    # Derived from IS_DEVELOPMENT
    @property
    def RELOAD(self) -> bool:
        return self.IS_DEVELOPMENT

    @property
    def LOG_LEVEL(self) -> str:
        return "DEBUG" if self.IS_DEVELOPMENT else "INFO"

    @property
    def CORS_ORIGINS(self) -> list[str]:
        if not self.IS_DEVELOPMENT:
            return []
        env = os.getenv("CORS_ORIGINS")
        if env:
            return [o.strip() for o in env.split(",") if o.strip()]
        return [
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "http://localhost:3000",
            "tauri://localhost",
        ]

    @property
    def DOCS_URL(self) -> str | None:
        return "/docs" if self.IS_DEVELOPMENT else None

    @property
    def REDOC_URL(self) -> str | None:
        return "/redoc" if self.IS_DEVELOPMENT else None

    @property
    def ACCESS_LOG(self) -> bool:
        return self.IS_DEVELOPMENT

    # Embeddings
    EMBEDDING_DEVICE: str = Field(default="cpu")

    # Debug
    DEBUGPY: bool = Field(default=False)

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    # Qdrant
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333

    # Postgres
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "memoryrag"
    POSTGRES_PASSWORD: str = "memoryrag"
    POSTGRES_DB: str = "memoryrag"

    # Nginx
    NGINX_HOST: str = "nginx"
    NGINX_PORT: int = 80

    # Ollama
    OLLAMA_HOST: str = "localhost"
    OLLAMA_PORT: int = 11434
    OLLAMA_MODEL_OCR: str = "glm-ocr:latest"
    OLLAMA_MODEL_FORMAT: str = "qwen3:14b"
    OLLAMA_MODEL_TRANSLATION: str = "qwen3:14b"
    OLLAMA_TIMEOUT: int = 600

    # Brain Storage
    BRAIN_PATH: str = "./brain"
    BRAIN_WORKSPACES_PATH: str = "./brain/workspaces"

    @property
    def REQUIRED_DIRS(self) -> list[str]:
        """Full paths of all required directories for startup validation."""
        return [self.BRAIN_PATH]

    @property
    def BRAIN_WORKSPACE_SUBDIRS(self) -> list[str]:
        """Per-workspace subdirectory layout."""
        return ["files", "translation/english", "translation/japanese"]

    def workspace_path(self, workspace_id: str) -> str:
        """Return the filesystem root for a workspace (creates subdirs on call)."""
        return str(Path(self.BRAIN_WORKSPACES_PATH) / workspace_id)

    def workspace_subdir(self, workspace_id: str, subdir: str) -> str:
        """Return a specific subdirectory path under a workspace."""
        return str(Path(self.BRAIN_WORKSPACES_PATH) / workspace_id / subdir)

    @property
    def DATABASE_URL(self) -> str:
        """Async PostgreSQL connection URL."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def REQUIRED_SERVICES(self) -> list[tuple[str, int]]:
        """(host, port) tuples for startup health checks."""
        return [
            (self.REDIS_HOST, self.REDIS_PORT),
            (self.POSTGRES_HOST, self.POSTGRES_PORT),
        ]

    # Upload Staging
    UPLOAD_PATH: str = "./storage/uploads"
    TEMP_PATH: str = "./temp_storage"
    TEMP_OCR_PATH: str = "./temp_storage/ocr"

    def temp_workspace_path(self, workspace_id: str) -> str:
        """Return the temp storage root for a workspace's staging files."""
        return str(Path(self.TEMP_PATH) / workspace_id)

    # Celery
    CELERY_TASK_ALWAYS_EAGER: bool = Field(default=False)

    @property
    def CELERY_BROKER_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/1"

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/2"

    @model_validator(mode="after")
    def _resolve_paths_to_absolute(self) -> "Settings":
        self.BRAIN_PATH = str(Path(self.BRAIN_PATH).resolve())
        self.BRAIN_WORKSPACES_PATH = str(Path(self.BRAIN_WORKSPACES_PATH).resolve())
        self.TEMP_PATH = str(Path(self.TEMP_PATH).resolve())
        self.TEMP_OCR_PATH = str(Path(self.TEMP_OCR_PATH).resolve())
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
