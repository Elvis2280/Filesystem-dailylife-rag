# orchestration/websocket_events.py

def publish_event(
    job_id: str,
    event: str,
    data: dict = None,
):
    """
    Placeholder event publisher.

    Later this can publish to:
    - WebSocket
    - Redis Pub/Sub
    - Kafka
    - RabbitMQ
    """

    print(
        f"[EVENT] "
        f"job_id={job_id} "
        f"event={event} "
        f"data={data}"
    )


def emit_pipeline_started(
    file_path: str,
):
    print(
        f"[PIPELINE STARTED] {file_path}"
    )


def emit_pipeline_completed(
    file_path: str,
):
    print(
        f"[PIPELINE COMPLETED] {file_path}"
    )


def emit_pipeline_failed(
    file_path: str,
    error: str,
):
    print(
        f"[PIPELINE FAILED] "
        f"{file_path} "
        f"error={error}"
    )