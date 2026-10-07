import logging
from pathlib import PurePosixPath

from lingua import Language, LanguageDetectorBuilder
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.constant import FilePipelineStage, LanguageOptions
from app.models.document import Document
from app.models.document_event import DocumentEventModel
from app.models.document_split import DocumentSplitModel
from app.models.translation import TranslationModel
from app.services.format.format_llm import format_markdown
from app.services.language.translation import translate_content
from app.services.storage.file_metadata import (
    markdown_object_key,
    translation_object_key,
)
from app.services.storage.object_storage import get_text, put_text

logger = logging.getLogger("memory_rag.format")

List_Lang: list[LanguageOptions] = [LanguageOptions.ENGLISH, LanguageOptions.JAPANESE]
TRANSLATE_CONFIDENCE_THRESHOLD = 0.95
_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        _detector = LanguageDetectorBuilder.from_languages(
            Language.ENGLISH, Language.JAPANESE
        ).build()
    return _detector


def _should_translate(page_text: str, target_language: LanguageOptions) -> bool:
    if target_language not in (LanguageOptions.ENGLISH, LanguageOptions.JAPANESE):
        return True
    detector = _get_detector()
    language = (
        Language.ENGLISH
        if target_language == LanguageOptions.ENGLISH
        else Language.JAPANESE
    )
    return (
        detector.compute_language_confidence(page_text, language)
        < TRANSLATE_CONFIDENCE_THRESHOLD
    )


def _splits_for_document(
    document_id: str, db_session: Session
) -> list[DocumentSplitModel]:
    return (
        db_session.execute(
            select(DocumentSplitModel)
            .join(Document, Document.id == DocumentSplitModel.document_id)
            .where(
                or_(
                    Document.id == document_id,
                    and_(
                        Document.parent_document_id == document_id,
                        Document.file_role == "converted_pdf",
                    ),
                )
            )
            .order_by(DocumentSplitModel.page_number)
        )
        .scalars()
        .all()
    )


def format_all_markdown(
    workspace_id: str, document_id: str, db_session: Session
) -> None:
    splits = _splits_for_document(document_id, db_session)
    if not splits:
        raise ValueError(f"No document splits found for document {document_id}")

    for split in splits:
        if not split.ocr_storage_key:
            raise ValueError(f"Missing OCR output for split {split.id}")
        page_text = get_text(split.ocr_storage_key)
        original_markdown = format_markdown(page_text)
        original_key = markdown_object_key(
            workspace_id,
            document_id,
            split.page_number,
        )
        split.markdown_storage_key = original_key
        split.markdown_size = put_text(
            original_markdown,
            original_key,
            "text/markdown",
        )
        db_session.add(
            DocumentEventModel(
                document_id=document_id,
                workspace_id=workspace_id,
                document_split_id=split.id,
                status="markdown_created",
                stage=FilePipelineStage.CREATING_MARKDOWN_FILES.value,
                step=FilePipelineStage.CREATING_MARKDOWN_FILES.step,
                message=f"Original Markdown for page {split.page_number} persisted in Garage",
                page_number=split.page_number,
            )
        )
        db_session.commit()

        for language in List_Lang:
            try:
                translated_text = (
                    translate_content(page_text, language)
                    if _should_translate(page_text, language)
                    else page_text
                )
                translated_markdown = format_markdown(translated_text)
                object_key = translation_object_key(
                    workspace_id,
                    document_id,
                    language.value,
                    split.page_number,
                )
                _save_translation(
                    translated_markdown,
                    object_key,
                    split,
                    language.value,
                    document_id,
                    db_session,
                )
            except Exception as exc:
                split.status = "failed"
                split.last_error = str(exc)
                db_session.commit()
                logger.error(
                    "Failed to format split %s for language %s: %s",
                    split.id,
                    language.value,
                    exc,
                )
                raise RuntimeError(
                    f"Failed to translate page {split.page_number} to {language.value}"
                ) from exc

        split.status = "completed"
        split.last_error = None
        db_session.commit()


def _save_translation(
    content: str,
    object_key: str,
    split: DocumentSplitModel,
    language: str,
    root_document_id: str,
    db_session: Session,
) -> TranslationModel:
    translation = db_session.execute(
        select(TranslationModel).where(
            TranslationModel.document_split_id == split.id,
            TranslationModel.language == language,
        )
    ).scalar_one_or_none()
    size = put_text(content, object_key, "text/markdown")
    if translation is None:
        translation = TranslationModel(
            workspace_id=split.workspace_id,
            document_split_id=split.id,
            language=language,
            filename=PurePosixPath(object_key).name,
            storage_key=object_key,
            file_type="text/markdown",
            size=size,
        )
    translation.filename = PurePosixPath(object_key).name
    translation.storage_key = object_key
    translation.file_type = "text/markdown"
    translation.size = size
    translation.status = "completed"
    translation.last_error = None
    translation.attempt_count = (translation.attempt_count or 0) + 1
    db_session.add(translation)
    db_session.flush()
    db_session.add(
        DocumentEventModel(
            document_id=root_document_id,
            workspace_id=split.workspace_id,
            document_split_id=split.id,
            translation_id=translation.id,
            status="translation_completed",
            stage=FilePipelineStage.TRANSLATION.value,
            step=FilePipelineStage.TRANSLATION.step,
            message=(
                f"{language} translation for page {split.page_number} "
                "persisted in Garage"
            ),
            page_number=split.page_number,
        )
    )
    db_session.commit()
    db_session.refresh(translation)
    return translation
