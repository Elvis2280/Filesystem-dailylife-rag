# orchestration/job_queue.py

from queue import Queue


ingestion_queue = Queue()


def enqueue_job(
    file_path,
):
    """
    Add ingestion job to queue.
    """

    ingestion_queue.put(
        file_path
    )


def dequeue_job():
    """
    Get next ingestion job.
    """

    return ingestion_queue.get()