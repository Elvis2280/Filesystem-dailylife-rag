# AGENTS.md - Memory RAG

## Run Commands

```bash
# API server
uvicorn main:app --reload

# Celery worker (separate terminal)
celery -A workers.celery_app worker --loglevel=info

# Tests
pytest

# Lint & Format
ruff check .
ruff format .
```

## Architecture

- **API**: FastAPI in `main.py` - handles REST + WebSocket, dispatches to Celery workers
- **Workers**: Celery tasks in `workers/` - async pipeline: ocr → translation → embedding → indexing
- **Orchestrator**: Event-driven workflow coordinator in `app/orchestrator/`
- **Client**: OpenCLAW (external AI agent) calls via REST + WebSocket

## Memory Layers

| Layer | Storage | Purpose |
|-------|---------|---------|
| Hot/Temporal | Redis | Quick embeddings, session data, task status |
| Vector | Qdrant | Dense semantic embeddings for retrieval |
| Relational | Postgres | Document metadata, relationships |

## Pipeline

1. Upload → detect language → store in `brain/english/` + `brain/japanese/`
2. Quick embedding → Redis (hot data)
3. Async: ocr → translation → chunking → embedding → indexing → Qdrant + Redis
4. Bilingual: EN input → JA copy + both embeddings; JA input → EN copy + both embeddings

## Key Files

- `app/core/config.py` - Settings (Redis, Qdrant, Postgres, Celery)
- `app/services/` - Pure business logic (no FastAPI/Celery deps)
- `app/orchestrator/` - Event-driven pipeline coordination
- `workers/` - Celery async tasks (OCR, translation, embedding, indexing, chunking)
- `.env` - Environment variables (create manually; see Setup section)

## Setup

```bash
# Dependencies
pip install -r requirements.txt

# External services (Redis, Qdrant)
docker-compose up -d

# Create .env with only overrides (optional):
#   IS_DEVELOPMENT=true          # Enable dev mode (auto-reload, debug logs, etc.)
# All other settings use sensible defaults from app/core/config.py
```

## Code Review Guidelines

When reviewing code, act as a **senior developer mentor**. Teach by explaining *why* something is a problem, not just *what* is wrong.

### Review Areas

| Category | What to Check |
|----------|---------------|
| **Logic** | Bugs, edge cases, incorrect flow, race conditions |
| **Clean Code** | Function size, naming, SRP, DRY, duplicated code |
| **Architecture** | Separation of concerns, module boundaries, dependency direction |
| **FastAPI** | Proper routing, dependency injection, async/await usage |
| **Celery** | Task design, retry logic, chain vs chord usage |
| **Python** | Type hints, exception handling, context managers |
| **Security** | Input validation, SQL/parameter injection, secrets handling |
| **Database** | Query optimization, connection pooling, transactions |
| **Performance** | N+1 queries, unnecessary iterations, caching |
| **API Design** | RESTful conventions, status codes, pagination |

### Review Response Format

```markdown
## Code Review: <filename>

### 🔴 Critical (fix immediately)
- Issue: [what] → Why: [explanation] → Fix: [suggestion]

### 🟡 Warnings (should fix)
- Issue: [what] → Suggestion: [improvement]

### 💡 Optimizations (nice to have)
- Tip: [suggestion with rationale]

### ✅ Good Practices
- What they're doing well
```

### Principles

1. **Explain the "why"** - Don't just say "use async", explain when/why it matters
2. **Prioritize** - Critical issues first, then warnings, then suggestions
3. **Offer alternatives** - Show better code, not just criticism
4. **Be constructive** - Acknowledge good patterns before pointing out issues
5. **Reference docs** - Link to official best practices when relevant