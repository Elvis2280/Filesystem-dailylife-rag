
from pathlib import Path

from ollama import chat


def image_extract(file_path: Path) -> str:
    try:
        response = chat(
            model="glm-ocr",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract all visible text from this image "
                        "exactly as it appears."
                    ),
                    "images": [str(file_path)],
                }
            ],
            options={
                "num_ctx": 20480,
                "num_predict": 2048,
                "temperature": 0,
            },
        )

        return response.message.content

    except Exception as e:
        raise RuntimeError(
            f"OCR failed: {e}"
        ) from e