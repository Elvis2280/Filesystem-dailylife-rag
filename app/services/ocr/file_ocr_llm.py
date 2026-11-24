"""Shared Ollama OCR for uploaded images and rendered document pages."""

import base64
import logging
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from PIL import Image

from app.core.config import settings
from app.core.prompts import OCR_PROMPT
from app.services.ai.model_preferences import ModelRole, get_model_name_sync

logger = logging.getLogger("memory_rag.ocr")
NATIVE_OCR_PROMPT = "Text Recognition:"
_RETRY_IMAGE_SIZE = (1600, 1600)
_CONTEXT_RESERVE = 512


def _read_ocr_image(
    source: str | Path | bytes, *, resize: bool = False
) -> tuple[str, int, int]:
    try:
        image_bytes = source if isinstance(source, bytes) else Path(source).read_bytes()
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
            if resize and max(width, height) > max(_RETRY_IMAGE_SIZE):
                with image.convert("RGB") as resized, BytesIO() as output:
                    resized.thumbnail(_RETRY_IMAGE_SIZE, Image.Resampling.LANCZOS)
                    resized.save(output, format="PNG")
                    image_bytes = output.getvalue()
                    width, height = resized.size
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise RuntimeError(f"Could not read OCR image: {exc}") from exc
    return base64.b64encode(image_bytes).decode("ascii"), width, height


def _request_ocr(
    client: httpx.Client,
    *,
    model: str,
    native: bool,
    image: str,
    num_ctx: int,
    num_predict: int,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": model,
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "temperature": 0,
        },
    }
    if native:
        endpoint = "/api/generate"
        request.update(prompt=NATIVE_OCR_PROMPT, images=[image])
    else:
        endpoint = "/api/chat"
        request.update(
            messages=[{"role": "user", "content": OCR_PROMPT, "images": [image]}],
            think=False,
        )

    response = client.post(endpoint, json=request)
    try:
        result = response.json()
    except ValueError:
        result = None
    if response.is_error:
        detail = result.get("error") if isinstance(result, dict) else None
        raise RuntimeError(
            f"Ollama generation failed (HTTP {response.status_code}): "
            f"{detail or response.reason_phrase}"
        )
    if not isinstance(result, dict):
        raise RuntimeError("Ollama returned an invalid OCR response")
    if result.get("error"):
        raise RuntimeError(f"Ollama generation failed: {result['error']}")
    return result


def extract_image_text(
    image_path: str | Path | bytes,
    *,
    model_name: str | None = None,
    document_id: str | None = None,
    page_number: int | None = None,
    on_retry: Callable[[], None] | None = None,
) -> str:
    """Return a complete transcription or raise with the final failure reason."""
    model = model_name or get_model_name_sync(ModelRole.OCR)
    family = model.rsplit("/", 1)[-1].split(":", 1)[0].casefold()
    native = family == "glm-ocr"
    num_ctx = settings.OLLAMA_OCR_NUM_CTX
    num_predict = settings.OLLAMA_OCR_NUM_PREDICT
    encoded, width, height = _read_ocr_image(image_path)
    context = f"document={document_id} page={page_number} model={model}"
    last_error: Exception | None = None
    reason = "OCR returned no response"

    # Use the complete URL to preserve a configured reverse proxy path prefix.
    with httpx.Client(
        base_url=settings.OLLAMA_URL, timeout=settings.OLLAMA_TIMEOUT
    ) as client:
        for attempt in (1, 2):
            started = perf_counter()
            retry = attempt == 1
            logger.info(
                "OCR request %s attempt=%d dimensions=%dx%d mode=%s "
                "num_ctx=%d num_predict=%d",
                context,
                attempt,
                width,
                height,
                "native" if native else "chat",
                num_ctx,
                num_predict,
            )
            try:
                result = _request_ocr(
                    client,
                    model=model,
                    native=native,
                    image=encoded,
                    num_ctx=num_ctx,
                    num_predict=num_predict,
                )
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                reason = str(exc)
                if isinstance(exc, httpx.TimeoutException):
                    reason = (
                        "Ollama OCR request timed out after "
                        f"{settings.OLLAMA_TIMEOUT} seconds"
                    )
                repeated_tokens = "token repeat limit reached" in reason.casefold()
                if retry and native and repeated_tokens:
                    encoded, width, height = _read_ocr_image(image_path, resize=True)
            else:
                last_error = None
                content = result.get("response")
                if not native:
                    message = result.get("message")
                    content = (
                        message.get("content") if isinstance(message, dict) else None
                    )
                text = content if isinstance(content, str) else ""
                done_reason = result.get("done_reason")
                input_tokens = result.get("prompt_eval_count")
                output_tokens = result.get("eval_count")
                logger.info(
                    "OCR response %s attempt=%d elapsed_seconds=%.3f "
                    "done=%s done_reason=%s input_tokens=%s output_tokens=%s "
                    "chars=%d blank=%s",
                    context,
                    attempt,
                    perf_counter() - started,
                    result.get("done"),
                    done_reason,
                    input_tokens,
                    output_tokens,
                    len(text),
                    not text.strip(),
                )
                if done_reason == "length":
                    reason = (
                        f"Ollama reached the OCR length limit (num_ctx={num_ctx}, "
                        f"num_predict={num_predict}, input_tokens={input_tokens}, "
                        f"output_tokens={output_tokens})"
                    )
                    if retry and isinstance(input_tokens, int) and input_tokens > 0:
                        retry_budget = min(
                            num_predict * 2, num_ctx - input_tokens - _CONTEXT_RESERVE
                        )
                        retry = retry_budget > num_predict
                        if retry:
                            num_predict = retry_budget
                    else:
                        retry = False
                elif result.get("done") is not True or done_reason != "stop":
                    reason = (
                        "Ollama OCR response did not finish normally "
                        f"(done_reason={done_reason})"
                    )
                elif not text.strip():
                    reason = "OCR returned empty or whitespace-only text"
                else:
                    logger.debug("OCR text %s preview=%r", context, text[:500])
                    return text

            logger.warning(
                "OCR attempt failed %s attempt=%d elapsed_seconds=%.3f reason=%s",
                context,
                attempt,
                perf_counter() - started,
                reason,
            )
            if not retry:
                break
            if on_retry is not None:
                on_retry()

    subject = (
        f" for page {page_number} of document {document_id}"
        if page_number is not None and document_id is not None
        else ""
    )
    attempts = "1 attempt" if attempt == 1 else "2 attempts"
    error = f"OCR failed{subject} after {attempts}: {reason}"
    raise RuntimeError(error) from last_error
