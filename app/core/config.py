from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Development flag
    IS_DEVELOPMENT: bool = Field(default=False)

    # App
    APP_NAME: str = "Personal Memory RAG"
    DEBUG: bool = False
    API_KEY: str | None = Field(default=None)
    CORS_ORIGINS_VALUE: str | None = Field(
        default=None, validation_alias="CORS_ORIGINS"
    )

    # Derived from IS_DEVELOPMENT
    @property
    def RELOAD(self) -> bool:
        return self.IS_DEVELOPMENT

    @property
    def LOG_LEVEL(self) -> str:
        return "DEBUG" if self.IS_DEVELOPMENT else "INFO"

    @property
    def CORS_ORIGINS(self) -> list[str]:
        if self.CORS_ORIGINS_VALUE:
            return [
                origin.strip()
                for origin in self.CORS_ORIGINS_VALUE.split(",")
                if origin.strip()
            ]
        if not self.IS_DEVELOPMENT:
            return []
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

    # Garage / S3-compatible object storage
    GARAGE_HOST: str = "garage"
    GARAGE_PORT: int = 3900
    OBJECT_STORAGE_ENDPOINT: str = "http://garage:3900"
    OBJECT_STORAGE_ACCESS_KEY: str = "GK00000000000000000000000000000000"
    OBJECT_STORAGE_SECRET_KEY: str = "0" * 64
    OBJECT_STORAGE_BUCKET: str = "memory-rag"
    OBJECT_STORAGE_REGION: str = "garage"

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
    OLLAMA_BASE_URL: str | None = None
    OLLAMA_HOST: str = "localhost"
    OLLAMA_PORT: int = 11434
    OLLAMA_MODEL_OCR: str = "glm-ocr:latest"
    OLLAMA_MODEL_FORMAT: str = "qwen3.5:9b"
    OLLAMA_MODEL_TRANSLATION: str = "qwen3.5:27b"
    OLLAMA_MODEL_CLEANER: str = "qwen3.5:9b"
    OLLAMA_MODEL_EMBEDDING: str = "bge-m3:latest"
    OLLAMA_MODEL_AGENT: str = "qwen3.5:9b"
    OLLAMA_TIMEOUT: int = 600

    @field_validator("OLLAMA_BASE_URL", mode="before")
    @classmethod
    def _normalize_ollama_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None

        base_url = str(value).strip().rstrip("/")
        if not base_url:
            return None

        parsed_url = urlsplit(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError(
                "OLLAMA_BASE_URL must be an absolute http:// or https:// URL"
            )
        try:
            parsed_url.port
        except ValueError as exc:
            raise ValueError("OLLAMA_BASE_URL contains an invalid port") from exc

        return base_url

    @property
    def OLLAMA_URL(self) -> str:
        """Return the configured Ollama URL or the legacy HTTP host and port."""
        if self.OLLAMA_BASE_URL:
            return self.OLLAMA_BASE_URL
        return f"http://{self.OLLAMA_HOST}:{self.OLLAMA_PORT}"

    @property
    def REQUIRED_DIRS(self) -> list[str]:
        """Full paths of all required directories for startup validation."""
        return [self.TEMP_PATH]

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
            (self.GARAGE_HOST, self.GARAGE_PORT),
        ]

    # Local scratch space. Durable files live in Garage.
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
        self.TEMP_PATH = str(Path(self.TEMP_PATH).resolve())
        self.TEMP_OCR_PATH = str(Path(self.TEMP_OCR_PATH).resolve())
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
