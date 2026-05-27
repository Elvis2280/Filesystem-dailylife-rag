# search/semantic_search.py

def semantic_search(
    query,
    db,
    k=5,
    threshold=0.75,
):
    """
    Semantic vector similarity search.

    Lower score = better match.
    """

    results = db.similarity_search_with_score(
        query,
        k=k,
    )

    filtered = []

    for doc, score in results:

        if score < threshold:

            filtered.append(
                {
                    "text": doc.page_content,
                    "source": doc.metadata.get(
                        "source"
                    ),
                    "page": doc.metadata.get(
                        "page"
                    ),
                    "score": float(score),
                    "search_type": "semantic",
                }
            )

    return filtered