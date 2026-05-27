# search/bm25_search.py

from gevent import os
from rank_bm25 import BM25Okapi
from fugashi import GenericTagger


tagger = GenericTagger(f"-r {os.getenv('MECABRC', '/etc/mecabrc')}")


def tokenize(text: str):
    """
    Japanese-aware tokenizer.
    """

    return [
        word.surface
        for word in tagger(text)
    ]


def bm25_search(
    query,
    db,
    k=5,
):
    """
    BM25 keyword/token search.

    High precision retrieval.
    """

    docs = list(
        db.docstore._dict.values()
    )

    corpus = [
        tokenize(
            d.page_content.lower()
        )
        for d in docs
    ]

    bm25 = BM25Okapi(corpus)

    tokenized_query = tokenize(
        query.lower()
    )

    scores = bm25.get_scores(
        tokenized_query
    )

    ranked = sorted(
        zip(docs, scores),
        key=lambda x: x[1],
        reverse=True,
    )

    results = []

    for doc, score in ranked[:k]:

        # Ignore poor matches
        if score <= 0:
            continue

        results.append(
            {
                "text": doc.page_content,
                "source": doc.metadata.get(
                    "source"
                ),
                "page": doc.metadata.get(
                    "page"
                ),
                "score": float(score),
                "search_type": "bm25",
            }
        )

    return results