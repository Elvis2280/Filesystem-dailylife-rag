from pathlib import Path

from pydantic import Field
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
        return ["*"] if self.IS_DEVELOPMENT else []

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
    OLLAMA_TIMEOUT: int = 600

    # Brain Storage
    BRAIN_PATH: str = "./brain"
    BRAIN_ENGLISH_PATH: str = "./brain/english"
    BRAIN_JAPANESE_PATH: str = "./brain/japanese"

    # Directory structure
    BRAIN_WORKSPACE_SUBDIRS: list[str] = Field(
        default=[
            "english/work",
            "english/personal",
            "japanese/work",
            "japanese/personal",
        ]
    )

    @property
    def REQUIRED_DIRS(self) -> list[str]:
        """Full paths of all required directories for startup validation."""
        base = Path(self.BRAIN_PATH)
        return [str(base / subdir) for subdir in self.BRAIN_WORKSPACE_SUBDIRS]

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

    # Celery
    CELERY_TASK_ALWAYS_EAGER: bool = Field(default=False)

    @property
    def CELERY_BROKER_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/1"

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/2"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
