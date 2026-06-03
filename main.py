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

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api.routes.workspace import router as workspace_router
from app.api.routes.file import router as file_router

from app.core.requirements_checker import validate_all
from app.core.logging import configure_logging

# CORS middleware is only needed in development for frontend dev servers
if settings.IS_DEVELOPMENT:
    from fastapi.middleware.cors import CORSMiddleware
    from app.api.routes.ollama import router as ollama_router

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url=settings.DOCS_URL,
    redoc_url=settings.REDOC_URL,
)

# Allow cross-origin requests from development frontend (e.g., localhost:3000)
if settings.IS_DEVELOPMENT:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Allow API Endpoints if is_development is True
if settings.IS_DEVELOPMENT:
    app.include_router(ollama_router)

# Register API route modules
app.include_router(workspace_router)
app.include_router(file_router)


@app.on_event("startup")
async def startup_event():
    """Validate all external services and directories on application startup.

    Checks Redis, Qdrant, Postgres, and Ollama connectivity.
    Ensures required base directories exist.
    Raises RuntimeError if any critical service is unreachable.

    Raises:
        RuntimeError: If one or more required services are not reachable.
    """
    logger = configure_logging(settings.LOG_LEVEL)
    report = await validate_all()

    # --- Directory Validation ---
    dir_report = report["directories_created"]
    if dir_report["status"] == "satisfied":
        logger.info("All base directories already satisfied")
    elif dir_report["status"] == "missing":
        logger.warning("Missing directories: %s", dir_report["paths"])

    # --- Service Connectivity Checks ---
    # Collect all failures to report them at once, rather than failing early
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
    # Ollama is optional for non-OCR features, so we warn instead of hard-failing
    from app.services.ai.ollama_client import OllamaClient

    ollama = OllamaClient()
    health_resp = await ollama.health_check()
    if health_resp.is_reachable:
        logger.info(
            "Ollama: connected at %s:%d", settings.OLLAMA_HOST, settings.OLLAMA_PORT
        )
        if settings.OLLAMA_MODEL_OCR in health_resp.available_models:
            logger.info("Ollama model '%s' is available", settings.OLLAMA_MODEL_OCR)
        else:
            logger.warning(
                "Ollama model '%s' is NOT available", settings.OLLAMA_MODEL_OCR
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
