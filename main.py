"""Memory RAG - FastAPI Application Entry Point.

A bilingual (English/Japanese) Retrieval-Augmented Generation system that
processes uploaded documents through an async pipeline: OCR → translation →
chunking → embedding → indexing. Uses FastAPI for the REST + WebSocket API,
with Celery workers handling the heavy async processing.

Architecture:
    ┌──────────┐     ┌─────────────┐     ┌──────────────────┐
    │  Client  │────▶│  FastAPI     │────▶│  Celery Workers  │
    │ (OpenCLAW)│     │  (main.py)   │     │  (workers/)      │
    └──────────┘     └─────────────┘     └──────────────────┘
                           │                       │
                           ▼                       ▼
                    ┌──────────────┐     ┌──────────────────┐
                    │   Services   │     │  Storage Layers  │
                    │  (app/services)    │ Redis/Qdrant/PG  │
                    └──────────────┘     └──────────────────┘

Startup Validation:
    On startup, verifies all external services are reachable
    (Redis, Qdrant, Postgres, Ollama) and required directories exist.
    Raises RuntimeError if any critical dependency is missing.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.document import router as document_router
from app.api.routes.workspace import router as workspace_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.requirements_checker import validate_all


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup & shutdown lifecycle for the application.

    Startup:
        Validates all external services (Redis, Qdrant, Postgres, Ollama)
        and required directories. Raises RuntimeError if any critical
        dependency is missing.

    Shutdown:
        Closes the async Redis client connection pool.
    """
    # ── Startup ──
    logger = configure_logging(settings.LOG_LEVEL)
    report = await validate_all()

    # --- Directory Validation ---
    dir_report = report["directories_created"]
    if dir_report["status"] == "satisfied":
        logger.info("All base directories already satisfied")
    elif dir_report["status"] == "missing":
        logger.warning("Missing directories: %s", dir_report["paths"])

    # --- Service Connectivity Checks ---
    errors = []
    for endpoint, is_up in report["services_status"].items():
        if is_up:
            logger.info(f"Service {endpoint} is reachable")
        else:
            logger.error(f"Service {endpoint} is NOT reachable")
            errors.append(f"Service {endpoint} is not reachable")

    # --- Postgres Database Check ---
    if report.get("postgres_db"):
        logger.info("Postgres DB: connected")
    else:
        logger.error("Postgres DB: connection failed")
        errors.append("Postgres DB connection failed")

    # --- Ollama Model Availability Check ---
    from app.services.ai.ollama_client import OllamaClient

    ollama = OllamaClient()
    health_resp = await ollama.health_check()
    if health_resp.is_reachable:
        logger.info(
            "Ollama: connected at %s:%d", settings.OLLAMA_HOST, settings.OLLAMA_PORT
        )
        # OCR Model Check
        if settings.OLLAMA_MODEL_OCR in health_resp.available_models:
            logger.info(
                "Ollama model '%s' for OCR is available", settings.OLLAMA_MODEL_OCR
            )
        else:
            logger.warning(
                "Ollama model '%s' for OCR is NOT available", settings.OLLAMA_MODEL_OCR
            )
        # Translation model Check
        if settings.OLLAMA_MODEL_TRANSLATION in health_resp.available_models:
            logger.info(
                "Ollama mode '%s' for Translation is available",
                settings.OLLAMA_MODEL_TRANSLATION,
            )
        else:
            logger.warning(
                "Ollama model '%s' for Translation is NOT available",
                settings.OLLAMA_MODEL_TRANSLATION,
            )
    else:
        logger.warning(
            "Ollama: NOT reachable at %s:%d. OCR and LLM features will be unavailable.",
            settings.OLLAMA_HOST,
            settings.OLLAMA_PORT,
        )

    # Fail fast if any critical dependency is missing
    if errors:
        raise RuntimeError("Startup validation failed: " + "; ".join(errors))

    yield  # ── Application runs here ──

    # ── Shutdown ──
    from app.core.redis_client import close_async_redis_client

    await close_async_redis_client()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url=settings.DOCS_URL,
    redoc_url=settings.REDOC_URL,
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register ollama routes only in dev mode
if settings.IS_DEVELOPMENT:
    from app.api.routes.ollama import router as ollama_router

    app.include_router(ollama_router)

# Register API route modules
app.include_router(workspace_router)
app.include_router(document_router)


@app.get("/")
def root():
    """Root endpoint returning a basic status message.

    Returns:
        JSONResponse: Simple health-check style response confirming the API is live.
    """
    return JSONResponse(content={"message": "Hello World", "status": "ok"})


@app.get("/health")
def health():
    """Health check endpoint for load balancers and monitoring.

    Returns:
        JSONResponse: Status indicating the application is running.
    """
    return JSONResponse(content={"status": "healthy"})


# Development server entry point — not used in production (gunicorn instead)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=settings.ACCESS_LOG,
    )
