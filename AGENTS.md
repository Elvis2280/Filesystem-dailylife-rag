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
- **Workers**: Celery tasks in `workers/tasks/` - async pipeline: save_file → ocr_task → translate_task → embed_task
- **Client**: OpenCLAW (external AI agent) calls via REST + WebSocket

## Memory Layers

| Layer | Storage | Purpose |
|-------|---------|---------|
| Long-term | Obsidian vault (`storage/vault/`) | Markdown + YAML frontmatter |
| Hot | Redis | Quick embeddings, session data |
| Vector | Qdrant | Dense semantic embeddings |

## Pipeline

1. Upload → save_file → ocr_task → translate_task → embed_task (×2 for EN/JA) → index to Qdrant+Redis → save Obsidian markdown (EN.md + JA.md with wiki links `[[filename]]`)
2. Bilingual: EN input → JA markdown + both embeddings; JA input → EN markdown + both embeddings

## Key Files

- `app/core/config.py` - Settings (Redis, Qdrant, Obsidian, Celery)
- `app/services/` - Pure business logic (no FastAPI/Celery deps)
- `workers/tasks/` - Celery async tasks
- `.env.example` - Required env vars template

## Setup

```bash
# Dependencies
pip install -r requirements.txt

# External services (Redis, Qdrant)
docker-compose up -d

# Copy env and configure
cp .env.example .env
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