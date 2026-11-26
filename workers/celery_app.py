from celery import Celery
from celery.signals import (
    worker_process_init,
    worker_process_shutdown,
    worker_ready,
    worker_shutdown,
)

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
import workers.tasks.save_data  # noqa: E402,F401 — Register task modules for Celery autodiscovery


@worker_process_init.connect
@worker_ready.connect
def start_model_preferences_listener(**kwargs) -> None:
    from app.services.ai.model_preferences import start_model_preference_listener

    start_model_preference_listener()


@worker_process_shutdown.connect
@worker_shutdown.connect
def stop_model_preferences_listener(**kwargs) -> None:
    from app.services.ai.model_preferences import stop_model_preference_listener

    stop_model_preference_listener()
