"""Private, single replica dispatcher for the server's shared Ollama instance."""

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import time

import anyio
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from redis.exceptions import RedisError
from starlette.types import Receive, Scope, Send

from app.api.routes.chat import ChatRequest, _require_workspace, complete_chat
from app.core.config import settings
from app.core.database import async_session
from app.core.logging import configure_logging
from app.services.chat.jobs import MAX_PENDING_JOBS, ChatJob, chat_jobs

logger = logging.getLogger("memory_rag.inference")

_METADATA = {
    ("GET", "/api/tags"),
    ("GET", "/api/ps"),
    ("GET", "/api/version"),
    ("POST", "/api/show"),
    ("GET", "/v1/models"),
}
_INFERENCE = {
    "/api/chat",
    "/api/generate",
    "/api/embed",
    "/api/embeddings",
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/responses",
}


@dataclass(slots=True)
class DocumentTurn:
    queued_at: float
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)


async def _run_chat(job: ChatJob) -> None:
    started = time()
    logger.info(
        "Chat job %s dispatched queue_wait=%.2fs", job.id, started - job.queued_at
    )
    try:
        if started - job.queued_at >= settings.INFERENCE_QUEUE_TIMEOUT_SECONDS:
            raise HTTPException(
                status_code=504, detail="The chat job expired in the inference queue"
            )
        request = ChatRequest(workspace_id=job.workspace_id, message=job.message or "")
        async with async_session() as db:
            await _require_workspace(request, db)
            answer = await complete_chat(request, db)
    except HTTPException as exc:
        # Keep internal upstream hosts, diagnostic payloads, and other details in logs.
        logger.warning(
            "Chat job %s failed status=%d detail=%s",
            job.id,
            exc.status_code,
            exc.detail,
        )
        message = (
            str(exc.detail)
            if exc.status_code in {404, 422, 504}
            else "The backend could not answer this question."
        )
        error = {"status_code": exc.status_code, "message": message}
    except TimeoutError:
        error = {
            "status_code": 504,
            "message": "The inference server could not finish the answer in time.",
        }
    except Exception:
        logger.exception("Chat job %s failed", job.id)
        error = {
            "status_code": 503,
            "message": "The backend could not answer this question.",
        }
    else:
        await chat_jobs.finish(job.id, answer=answer.model_dump(mode="json"))
        logger.info("Chat job %s completed execution=%.2fs", job.id, time() - started)
        return
    await chat_jobs.finish(job.id, error=error)


class Dispatcher:
    def __init__(self) -> None:
        self.documents: deque[DocumentTurn] = deque()
        self.wake = asyncio.Event()

    async def run(self) -> None:
        last_was_chat = False
        recover = True
        while True:
            self.wake.clear()
            while self.documents and self.documents[0].done.is_set():
                self.documents.popleft()

            if not (last_was_chat and self.documents):
                try:
                    if recover:
                        await chat_jobs.recover()
                        recover = False
                    job = await chat_jobs.claim()
                    if job is not None:
                        await _run_chat(job)
                        last_was_chat = True
                        continue
                except RedisError:
                    if not recover:
                        logger.exception("Chat queue connection lost")
                    recover = True
                    await asyncio.sleep(1)

            if self.documents:
                turn = self.documents.popleft()
                if not turn.done.is_set():
                    turn.ready.set()
                    await turn.done.wait()
                    last_was_chat = False
                continue

            # Redis lives in a separate process. Poll also wakes us for new chat jobs.
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=0.25)
            except TimeoutError:
                pass

    async def wait_for_document(self, request: Request) -> DocumentTurn:
        if len(self.documents) >= MAX_PENDING_JOBS:
            raise HTTPException(status_code=503, detail="The inference queue is full")
        loop = asyncio.get_running_loop()
        turn = DocumentTurn(queued_at=loop.time())
        self.documents.append(turn)
        self.wake.set()
        try:
            while not turn.ready.is_set():
                remaining = settings.INFERENCE_QUEUE_TIMEOUT_SECONDS - (
                    loop.time() - turn.queued_at
                )
                if remaining <= 0:
                    raise HTTPException(
                        status_code=504,
                        detail="The request expired in the inference queue",
                    )
                if await request.is_disconnected():
                    raise HTTPException(status_code=499, detail="Client disconnected")
                try:
                    await asyncio.wait_for(turn.ready.wait(), timeout=min(remaining, 1))
                except TimeoutError:
                    pass
            logger.info(
                "Background inference dispatched path=%s queue_wait=%.2fs",
                request.url.path,
                loop.time() - turn.queued_at,
            )
            return turn
        except BaseException:
            turn.done.set()
            raise


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.LOG_LEVEL)
    if settings.INFERENCE_BASE_URL:
        raise RuntimeError("The dispatcher must connect directly to shared Ollama")
    dispatcher = Dispatcher()
    app.state.dispatcher = dispatcher
    async with httpx.AsyncClient(
        base_url=settings.OLLAMA_URL,
        timeout=httpx.Timeout(settings.OLLAMA_TIMEOUT, connect=10),
    ) as upstream:
        app.state.upstream = upstream
        runner = asyncio.create_task(dispatcher.run())
        app.state.runner = runner
        try:
            yield
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
            await chat_jobs.redis.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    if request.app.state.runner.done():
        raise HTTPException(
            status_code=503, detail="Inference dispatcher is unavailable"
        )
    try:
        await chat_jobs.redis.ping()
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Chat queue unavailable") from exc
    return {"status": "healthy"}


class InferenceResponse(StreamingResponse):
    def __init__(self, upstream: httpx.Response, turn: DocumentTurn, deadline: float):
        self.upstream = upstream
        self.turn = turn
        self.deadline = deadline
        super().__init__(
            self.chunks(),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type"),
        )

    async def chunks(self) -> AsyncIterator[bytes]:
        # Deadline covers the full Ollama call, including streamed responses.
        chunks = self.upstream.aiter_bytes()
        while True:
            try:
                async with asyncio.timeout_at(self.deadline):
                    chunk = await anext(chunks)
            except StopAsyncIteration:
                return
            yield chunk

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await self.upstream.aclose()
                finally:
                    self.turn.done.set()


@app.api_route("/{endpoint:path}", methods=["GET", "POST"])
async def ollama_proxy(request: Request, endpoint: str) -> Response:
    path = "/" + endpoint
    metadata = (request.method, path) in _METADATA
    if not metadata and (request.method != "POST" or path not in _INFERENCE):
        raise HTTPException(status_code=404, detail="Unknown inference endpoint")

    upstream: httpx.AsyncClient = request.app.state.upstream
    dispatcher: Dispatcher = request.app.state.dispatcher
    body = await request.body()
    upstream_request = upstream.build_request(
        request.method,
        path,
        content=body,
        params=str(request.url.query),
        headers={
            "Content-Type": request.headers.get("content-type", "application/json")
        },
    )
    if metadata:
        try:
            async with asyncio.timeout(10):
                response = await upstream.send(upstream_request)
                return JSONResponse(response.json(), status_code=response.status_code)
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            raise HTTPException(
                status_code=502, detail="Ollama metadata unavailable"
            ) from exc

    turn = await dispatcher.wait_for_document(request)
    deadline = asyncio.get_running_loop().time() + settings.OLLAMA_TIMEOUT
    try:
        async with asyncio.timeout_at(deadline):
            response = await upstream.send(upstream_request, stream=True)
        return InferenceResponse(response, turn, deadline)
    except (TimeoutError, httpx.TimeoutException):
        turn.done.set()
        return JSONResponse({"error": "Ollama inference timed out"}, status_code=504)
    except httpx.HTTPError:
        turn.done.set()
        logger.exception("Ollama inference request failed")
        return JSONResponse({"error": "Ollama inference unavailable"}, status_code=502)
    except BaseException:
        turn.done.set()
        raise
