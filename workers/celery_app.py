from celery import Celery

from app.core.config import settings

celery_app = Celery("memory_rag")

celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_store_eager_result=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

import workers.tasks.file_pipeline  # noqa: E402,F401 — Register task modules for Celery autodiscovery
