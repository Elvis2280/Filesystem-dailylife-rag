# Memory RAG - Project Specification

## Overview

Memory RAG is an event-driven, orchestrated document processing pipeline with RAG-based question answering. It processes documents through OCR, translation, and embedding stages, storing results across multiple storage layers for efficient retrieval.

## Tech Stack

| Component | Technology | Version |
|-----------|------------|---------|
| API Framework | FastAPI | 0.136.1 |
| Task Queue | Celery | latest |
| Message Broker | Redis | latest |
| Vector Database | Qdrant | latest |
| OCR | GLM OCR | latest |
| Embeddings | BGE-M3 | latest |
| Translation | TBD | - |
| Server | Uvicorn | 0.46.0 |

## Architecture Flow

### Document Processing Pipeline

```
Upload (REST/WS) → save_file → ocr_task → translate_task →
  → embed_task (×2: EN + JA) → index to Qdrant + Redis
  → save Obsidian markdown (EN.md + JA.md with wiki links)
```

### Query Flow

```
User Query → API → RAG Service → Qdrant (vector search)
  → Build context → Return answer
```

### Client Interaction

```
External AI Agent (OpenCLAW)
        ↓ REST API + WebSocket
    FastAPI Server
        ↓ (async via Celery)
    Celery Workers
        ↓
    Qdrant + Redis + Obsidian Vault
```

## Memory Architecture

| Memory Type | Storage | Purpose |
|-------------|---------|---------|
| Long-term | Obsidian vault (markdown + YAML frontmatter) | Persistent, searchable text |
| Hot/Temporal | Redis | Quick access embeddings, session data |
| Vector | Qdrant | Heavy/dense semantic embeddings |

### Obsidian Storage Details

- **Structure**: By category/topic folders
- **Frontmatter Fields**: `id`, `title`, `date`, `lang`, `tags`, `source`
- **Linking**: Wiki links `[[filename]]` between EN ↔ JA pairs
- **Original files**: External storage only (not in vault)

## Folder Structure

```
memory-rag/
├── app/                      # Main application package
│   ├── api/                  # FastAPI routes and endpoints
│   │   ├── routes/
│   │   │   ├── documents.py  # Document upload, status, retrieval
│   │   │   ├── query.py     # RAG query endpoints
│   │   │   └── health.py    # Health check endpoints
│   │   └── dependencies/    # FastAPI dependency injection
│   ├── models/              # Pydantic schemas
│   │   ├── document.py      # Document request/response models
│   │   ├── query.py         # Query request/response models
│   │   └── response.py      # RAG response models
│   ├── services/            # Core business logic (pure Python)
│   │   ├── ocr/             # GLM OCR integration
│   │   ├── translation/     # Translation service
│   │   ├── embedding/       # BGE-M3 embedding service
│   │   ├── vector_store/    # Qdrant client wrapper
│   │   ├── redis_client/    # Redis client wrapper
│   │   ├── rag/             # RAG retrieval and answer generation
│   │   └── storage/
│   │       └── obsidian.py  # Obsidian vault handler
│   └── core/                # Configuration, logging, constants
├── workers/                 # Celery async workers
│   ├── tasks/
│   │   ├── save_file.py     # File storage async task
│   │   ├── ocr_task.py      # OCR processing task
│   │   ├── translate_task.py
│   │   └── embed_task.py    # Embedding task (Qdrant + Redis)
│   ├── celery_app.py        # Celery configuration
│   └── worker.py            # Worker entry point
├── storage/                 # Local file storage
│   ├── uploads/             # Uploaded documents
│   └── vault/               # Obsidian markdown vault
├── tests/                   # Test suite
│   ├── unit/                # Unit tests
│   └── integration/         # Integration tests
├── scripts/                 # Utility and maintenance scripts
├── pyproject.toml           # Project metadata and dependencies
├── docker-compose.yml       # Docker compose configuration
├── Dockerfile               # Container build configuration
├── README.md               # Project overview
├── PROJECT.md              # This file
└── .env.example            # Environment variables template
```

## Component Responsibilities

### `app/api/`

FastAPI HTTP/WebSocket layer. Handles incoming requests, validates input, returns responses. Dispatches long-running tasks to Celery workers.

**Files:**
- `routes/documents.py` - Document upload (`POST /documents`), status (`GET /documents/{id}`)
- `routes/query.py` - RAG query (`POST /query`)
- `routes/health.py` - Health check (`GET /`, `GET /health`)

### `app/models/`

Pydantic schemas for request/response validation. Ensures type safety across the API.

**Files:**
- `document.py` - DocumentUploadResponse, DocumentStatusResponse, DocumentInfo
- `query.py` - QueryRequest, QueryResponse, SourceDocument
- `response.py` - General response models

### `app/services/`

Pure business logic with no framework dependencies. Each service is self-contained and testable.

| Service | Responsibility |
|---------|-----------------|
| `ocr/` | GLM OCR text extraction from documents |
| `translation/` | Document translation (EN ↔ JA) |
| `embedding/` | BGE-M3 embedding generation |
| `vector_store/` | Qdrant CRUD operations (index, search, delete) |
| `redis_client/` | Redis operations (caching, sessions, quick embeddings) |
| `rag/` | Retrieval-augmented generation logic |
| `storage/obsidian.py` | Obsidian vault read/write with frontmatter + wiki linking |

### `workers/`

Celery tasks for async processing. Each task is a step in the pipeline:

| Task | Responsibility |
|------|----------------|
| `save_file.py` | Persist uploaded file to storage |
| `ocr_task.py` | Extract text via GLM OCR |
| `translate_task.py` | Translate text between EN/JA |
| `embed_task.py` | Generate embeddings and index to Qdrant + Redis |

**Files:**
- `celery_app.py` - Celery configuration and app initialization
- `worker.py` - Worker entry point

### `app/core/`

Application-wide settings and utilities.

**Files:**
- `config.py` - Settings management (Redis, Qdrant, Obsidian, Celery)
- `logging.py` - Logging configuration

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Welcome endpoint (Hello World) |
| GET | `/health` | Health check |
| POST | `/documents` | Upload a document |
| GET | `/documents/{id}` | Get document status |
| POST | `/query` | Query with RAG |
| WS | `/ws` | WebSocket for real-time updates |

## Pipeline Details

### Document Processing Steps

1. **Upload** - User submits document via REST API
2. **save_file** - File is stored in local storage, metadata saved to Redis
3. **ocr_task** - GLM OCR extracts text from document
4. **translate_task** - Translate document to opposite language
5. **embed_task** - Generate embeddings for both EN and JA versions
6. **Index** - Embeddings stored in Qdrant (heavy) + Redis (quick)
7. **Save Markdown** - Two files created: EN.md + JA.md with wiki links

### Bilingual Processing

- English input → Generate Japanese markdown + both embeddings
- Japanese input → Generate English markdown + both embeddings
- Both EN and JA embeddings stored in Qdrant for cross-language search

## Environment Variables

```env
# App
APP_NAME=Memory RAG
DEBUG=false

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Obsidian
OBSIDIAN_VAULT_PATH=./storage/vault

# Storage
UPLOAD_PATH=./storage/uploads

# Celery
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

## Development Guidelines

- Run API: `uvicorn main:app --reload`
- Run Worker: `celery -A workers.celery_app worker --loglevel=info`
- Tests: `pytest`
- Lint: `ruff check .`
- Format: `ruff format .`