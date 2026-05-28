from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api.routes.workspace import router as workspace_router
from app.api.routes.file import router as file_router
from app.core.requirements_checker import validate_all
from app.core.logging import configure_logging

if settings.IS_DEVELOPMENT:
    from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url=settings.DOCS_URL,
    redoc_url=settings.REDOC_URL,
)

if settings.IS_DEVELOPMENT:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(workspace_router)
app.include_router(file_router)


@app.on_event("startup")
async def startup_event():
    logger = configure_logging(settings.LOG_LEVEL)
    report = await validate_all()

    # Directory report
    dir_report = report["directories_created"]
    if dir_report["status"] == "satisfied":
        logger.info("All base directories already satisfied")
    elif dir_report["status"] == "missing":
        logger.warning("Missing directories: %s", dir_report["paths"])

    errors = []
    for endpoint, is_up in report["services_status"].items():
        if is_up:
            logger.info(f"Service {endpoint} is reachable")
        else:
            logger.error(f"Service {endpoint} is NOT reachable")
            errors.append(f"Service {endpoint} is not reachable")

    if report.get("postgres_db"):
        logger.info("Postgres DB: connected")
    else:
        logger.error("Postgres DB: connection failed")
        errors.append("Postgres DB connection failed")

    from app.services.ai.ollama_client import OllamaClient

    ollama = OllamaClient()
    if await ollama.health_check():
        logger.info(
            "Ollama: connected at %s:%d", settings.OLLAMA_HOST, settings.OLLAMA_PORT
        )
        if await ollama.is_model_available(settings.OLLAMA_MODEL_OCR):
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

    if errors:
        raise RuntimeError("Startup validation failed: " + "; ".join(errors))


@app.get("/")
def root():
    return JSONResponse(content={"message": "Hello World", "status": "ok"})


@app.get("/health")
def health():
    return JSONResponse(content={"status": "healthy"})


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
