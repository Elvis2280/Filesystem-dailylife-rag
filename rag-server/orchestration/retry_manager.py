# orchestration/retry_manager.py

import time


def retry_operation(
    operation,
    retries=3,
    delay=2,
):
    """
    Generic retry helper.

    Useful for:
    - OCR failures
    - embedding failures
    - network failures
    """

    last_error = None

    for attempt in range(retries):

        try:

            return operation()

        except Exception as e:

            last_error = e

            print(
                f"Retry "
                f"{attempt + 1}/{retries}"
            )

            time.sleep(delay)

    raise last_error