# Memory RAG

An event-driven, orchestrated document processing pipeline with RAG-based question answering.

## Overview

Memory RAG is a document processing system that handles OCR, translation, embedding, and retrieval. It uses an event-driven architecture with Celery workers to process documents asynchronously, storing embeddings in Qdrant (vector DB) and Redis.

## Tech Stack

| Component | Technology |
|-----------|------------|
| API Framework | FastAPI |
| Task Queue | Celery + Redis |
| Vector Database | Qdrant |
| Caching/Sessions | Redis |
| OCR | GLM OCR |
| Embeddings | BGE-M3 (local) |
| Translation | TBD |

## Architecture Flow

### Document Processing Pipeline

```
User Upload → API Endpoint → Celery Task: save_file
    → Task: ocr_task → Task: translate_task → Task: embed_task
    → Index to Qdrant + Redis
```

1. **Upload**: User submits document via REST API
2. **Save File**: File is stored in local storage, metadata saved to Redis
3. **OCR**: GLM OCR extracts text from document
4. **Translation**: Translated document (if needed)
5. **Embedding**: BGE-M3 generates embeddings
6. **Index**: Embeddings stored in Qdrant + Redis

### Query Flow

```
User Query → API → RAG Service → Qdrant (vector search)
    → Build context → Return answer
```

## Folder Structure

```
memory-rag/
├── app/                      # Main application package
│   ├── api/                  # FastAPI routes and endpoints
│   │   ├── routes/
│   │   │   ├── documents.py  # Document upload, status, retrieval
│   │   │   ├── query.py     # RAG query endpoints
│   │   │   └── health.py    # Health check endpoints
│   │   ├── ws/              # WebSocket route handlers
│   │   └── dependencies/    # FastAPI dependency injection
│   ├── core/                # Configuration, logging, constants
│   │   ├── config.py        # Pydantic Settings (Redis, Qdrant, Postgres, Celery)
│   │   └── logging.py       # Logging configuration
│   ├── models/              # Pydantic schemas
│   │   ├── document.py      # Document request/response models
│   │   ├── query.py         # Query request/response models
│   │   └── response.py      # General response models
│   ├── services/            # Business logic (pure Python)
│   │   ├── rag/             # RAG retrieval and answer generation
│   │   ├── retrieval/       # Vector search, document retrieval
│   │   ├── chunking/        # Document chunking logic
│   │   ├── language/        # Language detection, translation utils
│   │   ├── storage/         # File storage, metadata, Redis client
│   │   └── metadata/        # Document metadata management
│   ├── retrieval/           # Retrieval orchestration layer
│   ├── websocket/           # WebSocket connection manager
│   └── orchestrator/        # Event-driven pipeline coordination
│       ├── events/           # Event definitions (TBD)
│       ├── handlers/         # Event handlers
│       ├── workflows/        # Pipeline workflows
│       └── state_machine/    # Pipeline state machine
├── workers/                 # Celery async workers
│   ├── ocr/                 # GLM OCR tasks
│   ├── translation/         # Translation tasks
│   ├── embedding/           # BGE-M3 embedding tasks
│   ├── indexing/            # Qdrant indexing tasks
│   ├── chunking/            # Document chunking tasks
│   ├── tasks/               # Core pipeline tasks
│   ├── celery_app.py        # Celery configuration
│   └── worker.py            # Worker entry point
├── brain/                   # Bilingual document storage
│   ├── english/             # English documents
│   └── japanese/            # Japanese documents
├── tests/                   # Test suite
│   ├── unit/                # Unit tests
│   └── integration/         # Integration tests
├── scripts/                 # Utility and maintenance scripts
├── main.py                  # FastAPI application entry point
├── pyproject.toml           # Project metadata and dependencies
├── docker-compose.yml       # Docker compose configuration
├── docker-compose.dev.yml   # Development overrides
├── Dockerfile               # Container build configuration
└── README.md                # This file
```

**Note:** The `storage/` directory is a named Docker volume (not in the repo). It is auto-created by Docker Compose at runtime.

## Component Descriptions

### `app/api/`

FastAPI HTTP layer. Handles incoming requests, validates input, returns responses. Dispatches long-running tasks to Celery workers.

### `app/models/`

Pydantic schemas for request/response validation. Ensures type safety across the API.

### `app/services/`

Pure business logic with no framework dependencies. Each service is self-contained and testable:

- **ocr/**: GLM OCR text extraction
- **translation/**: Document translation
- **embedding/**: BGE-M3 embedding generation
- **vector_store/**: Qdrant CRUD operations
- **redis_client/**: Redis operations (caching, sessions, state)
- **rag/**: Retrieval-augmented generation logic

### `workers/`

Celery tasks for async processing. Each task is a step in the pipeline:

1. `save_file`: Persist uploaded file
2. `ocr_task`: Extract text via GLM OCR
3. `translate_task`: Translate text
4. `embed_task`: Generate embeddings and index to Qdrant + Redis

### `app/core/`

Application-wide settings: config management, logging setup, constants.

## Getting Started

### Prerequisites

- Python 3.12+
- Redis server
- Qdrant server
- Docker & Docker Compose (optional)

### Setup (Local Dev)

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the project root with overrides (optional):
   ```env
   IS_DEVELOPMENT=true
   ```
   > For **local development without Docker**, override service hosts:
   > ```env
   > REDIS_HOST=localhost
   > QDRANT_HOST=localhost
   > POSTGRES_HOST=localhost
   > ```
   > In Docker, the default service names (`redis`, `qdrant`, `postgres`) work automatically.
4. Start services:
   ```bash
   docker-compose up -d  # Redis, Qdrant
   ```
5. Run the API:
   ```bash
   uvicorn main:app --reload
   ```
6. Start Celery worker:
   ```bash
    celery -A workers.celery_app worker --loglevel=info
    ```

### Development Mode

Set `IS_DEVELOPMENT=true` in your `.env` file to enable development features:

| Feature | Dev (`true`) | Prod (`false`) | Description |
|---------|-------------|----------------|-------------|
| `RELOAD` | ✅ Auto-reload | ❌ Disabled | Uvicorn restarts on file changes |
| `LOG_LEVEL` | `DEBUG` | `INFO` | Verbose logging for debugging |
| `CORS_ORIGINS` | `["*"]` | `[]` | Allow all origins for local frontend |
| `DOCS_URL` | `/docs` | Disabled | FastAPI Swagger UI |
| `REDOC_URL` | `/redoc` | Disabled | Alternative API docs |
| `ACCESS_LOG` | ✅ Enabled | ❌ Disabled | Log every HTTP request |
| `CELERY_ALWAYS_EAGER` | ✅ Sync | ❌ Async | Run Celery tasks inline (no worker needed) |
| `EMBEDDING_DEVICE` | `cpu` | Auto-detect | Force CPU for consistent behavior |

#### Development Startup

```bash
# Ensure IS_DEVELOPMENT=true in .env

# Start with development overrides (API on localhost:8000 + --reload)
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
```

API available at:
- `http://localhost/` (via nginx)
- `http://localhost:8000/` (direct, for Postman/debugging)
- `http://localhost:8000/docs` (Swagger UI)
- `http://localhost:8000/redoc` (ReDoc)
- `http://localhost:5555` (Flower dashboard)

### Running with Docker (Production)

When `IS_DEVELOPMENT=false` (or unset), API is only accessible via nginx proxy. For development mode, see the [Development Mode](#development-mode) section above.

**Prerequisites:** Docker, Docker Compose.

#### CPU (default — macOS, cloud VMs, CPU-only machines)

```bash
# 1. Create .env manually (see Setup section above for required variables)

# 2. Build and start all services
docker-compose up --build -d
```

#### GPU (NVIDIA workstation/server)

**Prerequisites:** Docker, Docker Compose, NVIDIA Container Toolkit.

```bash
# 1. Create .env manually

# 2. Build and start with GPU worker
docker-compose --profile gpu up --build -d
```

**Useful commands:**

| Action | Command |
|--------|---------|
| Check status | `docker-compose ps` |
| View API logs | `docker-compose logs -f api` |
| View worker logs | `docker-compose logs -f worker` |
| View GPU worker logs | `docker-compose logs -f worker-gpu` |
| View all logs | `docker-compose logs -f` |
| Restart API | `docker-compose restart api` |
| Scale CPU workers | `docker-compose up -d --scale worker=3` |
| Scale GPU workers | `docker-compose --profile gpu up -d --scale worker-gpu=2` |
| Stop everything | `docker-compose down` |
| Stop + remove data | `docker-compose down -v` |
| Shell into API | `docker-compose exec api bash` |
| Verify GPU access | `docker-compose exec worker-gpu nvidia-smi` |

**First run:** Workers will download BGE-M3 model (~2GB). Monitor progress with `docker-compose logs -f worker`.

### Migrations

We use **Alembic** for database schema migrations. Migrations are **manual** — you must run them explicitly.

#### Create a Migration

After changing SQLAlchemy models in `app/models/`:

```bash
# Generate migration script
docker-compose exec api alembic revision --autogenerate -m "description of changes"

# Review the generated file in alembic/versions/ before applying!
```

#### Apply Migrations

```bash
# Upgrade to latest
docker-compose exec api alembic upgrade head

# Check current version
docker-compose exec api alembic current

# View migration history
docker-compose exec api alembic history
```

#### Rollback

```bash
# Downgrade one version
docker-compose exec api alembic downgrade -1

# Reset entirely (dev only!)
docker-compose exec api alembic downgrade base
```

#### Initial Setup

First time setting up the project:

```bash
# 1. Start services
docker-compose up -d

# 2. Apply all pending migrations
docker-compose exec api alembic upgrade head
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/documents` | Upload a document |
| GET | `/documents/{id}` | Get document status |
| POST | `/query` | Query with RAG |
| GET | `/health` | Health check |

## Development

### Testing

We use **pytest** with async support. The test suite is organized into unit and integration tests.

#### Running Tests

```bash
# All tests
pytest

# Unit tests only (no external services needed)
pytest -m unit

# Integration tests only (requires Postgres/Redis)
pytest -m integration

# With coverage report
pytest --cov=app --cov-report=term-missing
```

#### Test Markers

| Marker | Description | Requires |
|--------|-------------|----------|
| `unit` | Isolated unit tests | Nothing |
| `integration` | API endpoint and DB tests | Postgres |
| `slow` | ML inference, large models | GPU/CPU |

#### Test Database

Integration tests use a separate `test_memoryrag` database that is automatically created and cleaned up between test runs. This keeps your development data safe.

```bash
# Manually clean the test database
PGPASSWORD=memoryrag psql -h localhost -U memoryrag -d postgres -c "DROP DATABASE IF EXISTS test_memoryrag"
```

### Pre-commit Hooks

Pre-commit hooks run automatically before every `git commit` to catch issues early.

#### Setup (once per developer)

```bash
# Install pre-commit
pip install pre-commit

# Install git hooks
pre-commit install
```

#### Usage

After setup, hooks run automatically on every commit:

```bash
git add .
git commit -m "feat: add feature"
# Hooks run: ruff lint + format
# If formatting changed files, re-stage and commit again:
# git add . && git commit -m "feat: add feature"
```

#### What Hooks Run

| Hook | Action | On Failure |
|------|--------|------------|
| `ruff` | Lint check for bugs | ❌ Blocks commit |
| `ruff-format` | Auto-format code | ✅ Auto-fixes (re-stage needed) |

#### Bypass (Emergency Only)

```bash
git commit -m "fix: urgent hotfix" --no-verify
```

### Linting & Formatting

- Lint: `ruff check .`
- Format: `ruff format .`