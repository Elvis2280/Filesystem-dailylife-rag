# orchestration/workflow_manager.py
from pathlib import Path

from orchestration.pipeline_router import (
    route_pipeline,
)
from services.extract_file import (
    extract_file,  # Import your existing extraction service
)

from orchestration.websocket_events import (
    emit_pipeline_started,  # emits STARTED event to websocket
    emit_pipeline_completed, # emits COMPLETED event to websocket
    emit_pipeline_failed, # emits FAILED event to websocket
)


def start_ingestion_workflow(
    file_path: str,
    source_file: str,    # Added
    file_hash: str,      # Added
    page_number: int,    # Added
):
    """
    Main orchestration entrypoint.

    Controls:
    - routing
    - lifecycle
    - events
    - monitoring
    """

    pipeline = route_pipeline(file_path)

    # Extract the actual text content using your extract_file service
    # We wrap file_path in Path() since extract_file expects a Path object
    extracted_text = extract_file(Path(file_path))

    # Pass all required parameters to the pipeline function
    return pipeline(
        extracted_text,
        source_file, 
        file_hash, 
        page_number
    )

   