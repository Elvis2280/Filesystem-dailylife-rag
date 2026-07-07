import logging
import re
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constant import LanguageOptions
from app.models.file_conversions import FileConversionModel
from app.services.format.format_llm import format_markdown
from app.services.language.translation import translate_content

logger = logging.getLogger("memory_rag.format")

List_Lang: list[LanguageOptions] = [LanguageOptions.ENGLISH, LanguageOptions.JAPANESE]


def format_all_markdown(
    workspace_id: str,
    document_id: str,
    db_session: Session,
) -> None:
    txt_records = (
        db_session.execute(
            select(FileConversionModel)
            .where(
                and_(
                    FileConversionModel.file_id == document_id,
                    FileConversionModel.converted_to_extension == "txt",
                )
            )
            .order_by(FileConversionModel.converted_file_path)
        )
        .scalars()
        .all()
    )

    if not txt_records:
        raise ValueError(
            f"No files txt for this operation. "
            f"document_id={document_id} workspace_id={workspace_id}"
        )

    translation_dirs = {
        LanguageOptions.ENGLISH: Path(
            settings.workspace_subdir(workspace_id, "translation/english")
        ),
        LanguageOptions.JAPANESE: Path(
            settings.workspace_subdir(workspace_id, "translation/japanese")
        ),
    }
    for d in translation_dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    original_dir = Path(settings.workspace_subdir(workspace_id, "files"))
    original_dir.mkdir(parents=True, exist_ok=True)

    for txt_record in txt_records:
        try:
            with open(txt_record.converted_file_path, "r", encoding="utf-8") as f:
                page_text = f.read()
        except OSError as e:
            logger.error("Failed to read txt file for document %s: %s", document_id, e)
            continue

        page_number = _extract_page_number(txt_record.converted_file_path, document_id)
        base_filename = f"{document_id}_page_{page_number:03d}"

        # Original language markdown (no translation)
        try:
            print(f"Formatting original page {page_number} for document {document_id}")
            print(f"Page text: {page_text[:100]}...")
            original_md = format_markdown(page_text)
            original_path = original_dir / f"{base_filename}.md"
            _save_md(original_path, original_md, document_id, db_session)
        except Exception as e:
            logger.error(
                "Failed to format original page %d for document %s: %s",
                page_number,
                document_id,
                e,
            )

        for lang in List_Lang:
            try:
                translated_text = translate_content(page_text, lang)
                translated_md = format_markdown(translated_text)
            except Exception as e:
                logger.error(
                    "Failed to process page %d for language %s on document %s: %s",
                    page_number,
                    lang.value,
                    document_id,
                    e,
                )
                continue

            md_path = translation_dirs[lang] / f"{base_filename}.md"
            _save_md(md_path, translated_md, document_id, db_session)


def _save_md(path: Path, content: str, document_id: str, db_session: Session) -> None:
    if not path.exists():
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            logger.error(
                "Failed to write md file %s for document %s: %s",
                path,
                document_id,
                e,
            )
            return

    existing = (
        db_session.execute(
            select(FileConversionModel).where(
                and_(
                    FileConversionModel.file_id == document_id,
                    FileConversionModel.converted_to_extension == "md",
                    FileConversionModel.converted_file_path == str(path),
                )
            )
        )
        .scalars()
        .first()
    )
    if existing:
        return

    record = FileConversionModel(
        file_id=document_id,
        converted_file_path=str(path),
        converted_mime_type="text/markdown",
        converted_to_extension="md",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)


def _extract_page_number(txt_path: str, document_id: str) -> int:
    match = re.search(r"_OCR_page_(\d+)\.txt$", txt_path)
    if match:
        return int(match.group(1))
    return 0
