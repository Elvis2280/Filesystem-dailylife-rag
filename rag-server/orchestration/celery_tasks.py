# orchestration/celery_tasks.py

from celery import Celery

from orchestration.workflow_manager import (
    start_ingestion_workflow,
)

celery_app = Celery(
    "rag_tasks",
    broker="redis://localhost:6379/0", #message broker
    backend="redis://localhost:6379/0",#result storage (backend)
)


@celery_app.task( # converts a normal Python function into a distributed task.
    bind=True,
    max_retries=3,
)
def ingest_file_task(
    self,
    file_path: str,
):
    """
    Async ingestion task.
    """

    try:

        return start_ingestion_workflow(
            file_path
        )

    except Exception as e:

        raise self.retry(
            exc=e,
            countdown=5,
        )