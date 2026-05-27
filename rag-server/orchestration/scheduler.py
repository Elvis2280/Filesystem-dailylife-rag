# orchestration/scheduler.py

import time

from orchestration.job_queue import (
    enqueue_job,
)


def scheduled_ingestion(
    file_paths,
    interval=5,
):
    """
    Simulate scheduled ingestion.

    Future:
    - cron
    - airflow
    - prefect
    """

    for file_path in file_paths:

        enqueue_job(
            file_path
        )

        print(
            f"Queued: {file_path}"
        )

        time.sleep(interval)