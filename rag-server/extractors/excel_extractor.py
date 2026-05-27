
import pandas as pd

from pathlib import Path

from extractors.common import logger


def excel_extract(file_path: Path) -> str:
    try:
        logger.info("Extracting Excel text...")

        sheets = pd.read_excel(
            file_path,
            sheet_name=None,
        )

        text_parts = []

        for sheet_name, df in sheets.items():

            sheet_text = (
                f"# Sheet: {sheet_name}\n"
                f"{df.to_string(index=False)}"
            )

            text_parts.append(sheet_text)

        return "\n\n".join(text_parts)

    except Exception as e:
        raise RuntimeError(
            f"Excel extraction failed: {e}"
        ) from e