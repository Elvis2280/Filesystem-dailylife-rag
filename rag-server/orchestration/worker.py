# orchestration/worker.py

from orchestration.job_queue import (
    dequeue_job,
)

from orchestration.workflow_manager import (
    start_ingestion_workflow,
)


def start_worker():
    """
    Background worker loop.
    """

    print("Worker started...")

    while True:

        file_path = dequeue_job()

        print(
            f"Processing: {file_path}"
        )

        try:

            start_ingestion_workflow(
                file_path
            )

        except Exception as e:

            print(
                f"Worker failed: {e}"
            )