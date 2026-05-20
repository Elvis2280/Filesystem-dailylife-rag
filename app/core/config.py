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

    @property
    def CELERY_TASK_ALWAYS_EAGER(self) -> bool:
        return self.IS_DEVELOPMENT

    # Embeddings
    EMBEDDING_DEVICE: str = Field(default="cpu")

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # Brain Storage
    BRAIN_PATH: str = "./brain"
    BRAIN_ENGLISH_PATH: str = "./brain/english"
    BRAIN_JAPANESE_PATH: str = "./brain/japanese"

    # Upload Staging
    UPLOAD_PATH: str = "./storage/uploads"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
