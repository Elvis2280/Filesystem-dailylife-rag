"""Language detection service using the Lingua library.

Classifies text content as English, Japanese, or Mixed by comparing
confidence scores from a Lingua language detector. A minimum confidence
threshold of 0.9 is required for a definitive classification; content
that falls below the threshold for both languages is classified as Mixed.

Used by the RAG pipeline for language-aware storage and retrieval
of bilingual (English/Japanese) documents.
"""

from lingua import Language, LanguageDetectorBuilder

from app.core.constant import LanguageOptions

# Minimum confidence threshold (0.0–1.0) required to classify content
# as a specific language. Content scoring below both thresholds is
# classified as LanguageOptions.MIXED.
MIN_ENGLISH_CONFIDENCE = 0.9
MIN_JAPANESE_CONFIDENCE = 0.9


def english_japanese_comparison(content: str) -> LanguageOptions:
    """Classify text content as English, Japanese, or Mixed.

    Uses a Lingua language detector configured for English and Japanese
    to compute confidence scores. Returns the language option whose
    confidence meets or exceeds the minimum threshold. If neither
    language meets the threshold, returns MIXED.

    Args:
        content: The text content to classify.

    Returns:
        LanguageOptions.ENGLISH if English confidence >= 0.9,
        LanguageOptions.JAPANESE if Japanese confidence >= 0.9,
        LanguageOptions.MIXED otherwise.
    """
    detector = LanguageDetectorBuilder.from_languages(
        Language.ENGLISH, Language.JAPANESE
    ).build()

    english_confidence = detector.compute_language_confidence(content, Language.ENGLISH)
    japanese_confidence = detector.compute_language_confidence(
        content, Language.JAPANESE
    )

    if english_confidence >= MIN_ENGLISH_CONFIDENCE:
        return LanguageOptions.ENGLISH
    elif japanese_confidence >= MIN_JAPANESE_CONFIDENCE:
        return LanguageOptions.JAPANESE
    else:
        return LanguageOptions.MIXED
