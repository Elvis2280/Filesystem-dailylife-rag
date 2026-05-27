# orchestration/pipeline_status.py

pipeline_status_store = {}


def update_pipeline_status(
    job_id: str,
    status: str,
):
    """
    Update pipeline status.
    """

    pipeline_status_store[job_id] = status


def get_pipeline_status(
    job_id: str,
):
    """
    Retrieve pipeline status.
    """

    return pipeline_status_store.get(
        job_id,
        "UNKNOWN",
    )