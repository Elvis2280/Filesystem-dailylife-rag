import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from pydantic import UUID4, BaseModel, Field, field_validator
from redis.exceptions import RedisError
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document
from app.models.document_split import DocumentSplitModel
from app.models.translation import TranslationModel
from app.models.workspace import WorkspaceModel
from app.services.ai.ollama_client import OllamaTimeoutError
from app.services.chat.agent import EmptyAgentResponseError
from app.services.chat.chat import (
    InvalidChatContextError,
    InvalidChatMessageError,
    NoResultsError,
    answer_chat,
)
from app.services.chat.jobs import (
    ChatJobConflict,
    ChatQueueFull,
    JobStatus,
    chat_jobs,
    receipt_job_id,
)

router = APIRouter(prefix="/api/v1", tags=["chat"])
logger = logging.getLogger("memory_rag.chat_api")


class ChatRequest(BaseModel):
    workspace_id: UUID
    message: str = Field(..., min_length=6)

    @field_validator("message")
    @classmethod
    def _message_not_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty")
        return value


class ChatSource(BaseModel):
    document_id: UUID
    page_number: int
    english_markdown_id: UUID
    japanese_markdown_id: UUID


class ChatResponse(BaseModel):
    response: str
    english_markdown_id: UUID | None
    japanese_markdown_id: UUID | None
    sources: list[ChatSource] = Field(default_factory=list)


class ChatJobError(BaseModel):
    status_code: int
    message: str


class ChatJobResponse(BaseModel):
    id: UUID
    status: JobStatus
    answer: ChatResponse | None = None
    error: ChatJobError | None = None


async def _resolve_markdown_ids(
    payload: dict[str, Any],
    workspace_id: UUID,
    db: AsyncSession,
) -> tuple[UUID, UUID]:
    """Find both completed translations for the matched document page."""
    try:
        match_workspace_id = UUID(str(payload["workspace_id"]))
        document_id = UUID(str(payload["document_id"]))
        page_number = payload["page_number"]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The top matching result has invalid page metadata",
        ) from exc

    if (
        match_workspace_id != workspace_id
        or not isinstance(page_number, int)
        or isinstance(page_number, bool)
        or page_number < 1
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The top matching result has invalid page metadata",
        )

    result = await db.execute(
        select(
            DocumentSplitModel.id,
            TranslationModel.language,
            TranslationModel.id,
        )
        .select_from(TranslationModel)
        .join(
            DocumentSplitModel,
            TranslationModel.document_split_id == DocumentSplitModel.id,
        )
        .join(Document, DocumentSplitModel.document_id == Document.id)
        .where(
            TranslationModel.workspace_id == match_workspace_id,
            TranslationModel.language.in_(("EN", "JP")),
            TranslationModel.status == "completed",
            DocumentSplitModel.workspace_id == match_workspace_id,
            DocumentSplitModel.page_number == page_number,
            or_(
                Document.id == document_id,
                Document.parent_document_id == document_id,
            ),
        )
        .order_by(
            case((DocumentSplitModel.document_id == document_id, 0), else_=1),
            DocumentSplitModel.id,
        )
    )

    translations_by_split: dict[UUID, dict[str, UUID]] = {}
    for split_id, language, translation_id in result.all():
        translations_by_split.setdefault(split_id, {})[language.upper()] = (
            translation_id
        )

    for translations in translations_by_split.values():
        if "EN" in translations and "JP" in translations:
            return translations["EN"], translations["JP"]

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Markdown translations were not found for the top matching page",
    )


async def _require_workspace(request: ChatRequest, db: AsyncSession) -> None:
    workspace_id = str(request.workspace_id)
    workspace_id_found = await db.scalar(
        select(WorkspaceModel.id).where(WorkspaceModel.id == request.workspace_id)
    )
    # Release the database connection before waiting for the model.
    await db.rollback()
    if workspace_id_found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workspace '{workspace_id}' not found",
        )


async def _create_chat_response(
    request: ChatRequest,
    db: AsyncSession,
    deadline: float,
) -> ChatResponse:
    """Generate a grounded answer and resolve its page citations."""
    workspace_id = str(request.workspace_id)
    try:
        chat_answer = await answer_chat(
            request.message, workspace_id, deadline=deadline
        )
    except InvalidChatMessageError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    except NoResultsError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except OllamaTimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(e),
        ) from e
    except EmptyAgentResponseError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e
    except InvalidChatContextError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e

    sources: list[ChatSource] = []
    seen_pages: set[tuple[str, int]] = set()
    for match in chat_answer.matches:
        payload = match.get("payload") or {}
        try:
            source_document_uuid = UUID(str(payload["document_id"]))
            source_page_number = payload["page_number"]
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="A cited result has invalid page metadata",
            )
        if not isinstance(source_page_number, int) or isinstance(
            source_page_number, bool
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="A cited result has invalid page metadata",
            )
        source_document_id = str(source_document_uuid)
        page_key = (source_document_id, source_page_number)
        if page_key in seen_pages:
            continue
        seen_pages.add(page_key)
        english_id, japanese_id = await _resolve_markdown_ids(
            payload,
            request.workspace_id,
            db,
        )
        sources.append(
            ChatSource(
                document_id=source_document_uuid,
                page_number=source_page_number,
                english_markdown_id=english_id,
                japanese_markdown_id=japanese_id,
            )
        )

    primary_source = sources[0] if sources else None

    return ChatResponse(
        response=chat_answer.response,
        english_markdown_id=(
            primary_source.english_markdown_id if primary_source else None
        ),
        japanese_markdown_id=(
            primary_source.japanese_markdown_id if primary_source else None
        ),
        sources=sources,
    )


async def complete_chat(request: ChatRequest, db: AsyncSession) -> ChatResponse:
    deadline = asyncio.get_running_loop().time() + settings.CHAT_REQUEST_TIMEOUT_SECONDS
    async with asyncio.timeout_at(deadline):
        return await _create_chat_response(request, db, deadline)


async def _submit_job(request: ChatRequest, receipt: UUID) -> UUID:
    if len(request.message.strip()) < 6:
        raise HTTPException(
            status_code=422, detail="Message must be at least 6 characters long"
        )
    try:
        return await chat_jobs.submit(
            request.workspace_id, request.message.strip(), receipt
        )
    except ChatJobConflict as exc:
        raise HTTPException(
            status_code=409, detail="Submission key is already in use"
        ) from exc
    except (ChatQueueFull, RedisError) as exc:
        raise HTTPException(
            status_code=503,
            detail="The chat queue is temporarily unavailable",
            headers={"Retry-After": "5"},
        ) from exc


async def _read_job(job_id: UUID) -> ChatJobResponse:
    try:
        job = await chat_jobs.get(job_id)
    except RedisError as exc:
        raise HTTPException(
            status_code=503, detail="The chat queue is temporarily unavailable"
        ) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Chat job not found")
    return ChatJobResponse(
        id=job.id,
        status=job.status,
        answer=ChatResponse.model_validate(job.answer)
        if job.answer is not None
        else None,
        error=ChatJobError.model_validate(job.error) if job.error is not None else None,
    )


@router.post("/chat/jobs", response_model=ChatJobResponse, status_code=202)
async def submit_chat_job(
    request: ChatRequest,
    response: Response,
    idempotency_key: UUID4 = Header(..., alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
) -> ChatJobResponse:
    """Accept a chat question that continues independently of the connection."""
    if not settings.INFERENCE_BASE_URL:
        raise HTTPException(
            status_code=503, detail="The inference dispatcher is not configured"
        )
    response.headers["Cache-Control"] = "no-store"
    await _require_workspace(request, db)
    job_id = await _submit_job(request, idempotency_key)
    return await _read_job(job_id)


@router.get("/chat/jobs/{job_id}", response_model=ChatJobResponse)
async def read_chat_job(
    job_id: UUID,
    response: Response,
    idempotency_key: UUID4 = Header(..., alias="Idempotency-Key"),
) -> ChatJobResponse:
    """Return the job only to callers possessing its original submission key."""
    response.headers["Cache-Control"] = "no-store"
    if receipt_job_id(idempotency_key) != job_id:
        raise HTTPException(status_code=404, detail="Chat job not found")
    return await _read_job(job_id)


async def _answer_for_connection(
    request: ChatRequest,
    db: AsyncSession,
    receipt: UUID | None,
) -> ChatResponse:
    if not settings.INFERENCE_BASE_URL:
        return await complete_chat(request, db)

    async with asyncio.timeout(settings.CHAT_REQUEST_TIMEOUT_SECONDS):
        job_id = await _submit_job(request, receipt or uuid4())
        while True:
            job = await _read_job(job_id)
            if job.answer is not None:
                return job.answer
            if job.error is not None:
                raise HTTPException(
                    status_code=job.error.status_code, detail=job.error.message
                )
            await asyncio.sleep(1)


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: UUID4 | None = Header(None, alias="Idempotency-Key"),
) -> ChatResponse:
    """Generate a grounded answer, waiting through backend warmup and retries."""
    await _require_workspace(request, db)
    try:
        return await _answer_for_connection(request, db, idempotency_key)
    except TimeoutError as exc:
        logger.warning("Chat deadline exceeded workspace=%s", request.workspace_id)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Chat answer generation exceeded the backend request deadline",
        ) from exc


def _sse(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


@router.post("/chat/stream", response_class=StreamingResponse)
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: UUID4 | None = Header(None, alias="Idempotency-Key"),
) -> StreamingResponse:
    """Stream progress heartbeats and then the regular grounded chat response.

    Clients should consume this POST response as a fetch stream. A successful
    response ends with one ``answer`` event containing the same fields as
    ``POST /api/v1/chat``; an ``error`` event means backend retries were
    exhausted or the request deadline elapsed.
    """
    await _require_workspace(request, db)

    async def events() -> AsyncIterator[str]:
        yield _sse(
            "progress",
            {"phase": "preparing", "message": "Preparing your answer"},
        )
        task = asyncio.create_task(_answer_for_connection(request, db, idempotency_key))
        try:
            while not task.done():
                done, _ = await asyncio.wait(
                    {task}, timeout=settings.CHAT_STREAM_HEARTBEAT_SECONDS
                )
                if not done:
                    yield _sse("heartbeat", {})
            response = task.result()
            yield _sse("answer", response.model_dump(mode="json"))
        except TimeoutError:
            logger.warning(
                "Chat stream deadline exceeded workspace=%s", request.workspace_id
            )
            yield _sse(
                "error",
                {
                    "code": "timeout",
                    "message": "The backend could not finish the answer before its deadline.",
                },
            )
        except HTTPException as exc:
            logger.info(
                "Chat stream ended with status=%d workspace=%s",
                exc.status_code,
                request.workspace_id,
            )
            yield _sse(
                "error",
                {"code": str(exc.status_code), "message": str(exc.detail)},
            )
        except asyncio.CancelledError:
            logger.info("Chat stream disconnected before answer completion")
            raise
        except Exception:
            logger.exception("Chat stream failed")
            yield _sse(
                "error",
                {
                    "code": "chat_failed",
                    "message": "The answer service could not complete the request after automatic recovery attempts.",
                },
            )
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
