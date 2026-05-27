# services/retrieval_service.py

import json
import sys

from search.hybrid_search import (
    hybrid_search,
)


def run(
    query: str,
):
    """
    Retrieval service entrypoint.
    """

    try:

        results = hybrid_search(
            query=query
        )

        return {
            "status": "success",
            "results": results,
            "message": "",
        }

    except Exception as e:

        return {
            "status": "error",
            "results": [],
            "message": str(e),
        }


if __name__ == "__main__":

    if len(sys.argv) < 2:

        print(
            json.dumps(
                {
                    "status": "error",
                    "results": [],
                    "message": "Missing query",
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        sys.exit(1)

    query = sys.argv[1]

    print(
        json.dumps(
            run(query),
            ensure_ascii=False,
            indent=2,
        )
    )