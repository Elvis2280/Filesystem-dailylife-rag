# AGENTS.md - Memory RAG Context & Rules

## Technical Stack & Execution Boundaries
- **Python 3.11+**: Use strict type hints (`dict[str, Any]`, `list[int]`).
- **FastAPI**: Endpoints in `main.py` or routing modules must be `async def`. Use Dependency Injection (`Depends`).
- **Celery**: Tasks in `workers/` run synchronously. **Never** directly call `async` service functions inside Celery workers without `asyncio.run()`.
- **Services Boundary**: Code in `app/services/` contains pure business logic and must remain decoupled from FastAPI and Celery frameworks.
- **Documentation Tooling**: When searching for framework docs or solving API issues, automatically look up documentation using the **Context7** tool for up-to-date API references.

## Common Developer Commands

```bash
# API Server
uvicorn main:app --reload

# Celery Worker (Separate terminal)
celery -A workers.celery_app worker --loglevel=info

# Tests & Quality Controls
pytest
ruff check .
ruff format .
