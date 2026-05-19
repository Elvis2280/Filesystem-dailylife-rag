# Memory RAG - Project Specification

## Overview

Memory RAG is an event-driven, orchestrated document processing pipeline with RAG-based question answering. It processes documents through OCR, translation, and embedding stages, storing results across multiple storage layers for efficient retrieval.

## Tech Stack

| Component       | Technology | Version |
| --------------- | ---------- | ------- |
| API Framework   | FastAPI    | 0.136.1 |
| Task Queue      | Celery     | latest  |
| Message Broker  | Redis      | latest  |
| Vector Database | Qdrant     | latest  |
| OCR             | GLM OCR    | latest  |
| Embeddings      | BGE-M3     | latest  |
| Translation     | TBD        | -       |
| Server          | Uvicorn    | 0.46.0  |

## Architecture Flow

### Document Processing Pipeline

```
Upload (REST/WS)
  ↓
save_file → detect language → store in brain/english/ + brain/japanese/
  ↓ (trigger: file_saved)
Quick Embedding → save to Redis (hot/quick data)
  ↓ (trigger: quick_embed_complete)
Async Pipeline (Celery):
  ocr_task → translate_task → embed_task (×2: EN + JA)
    ↓ (trigger: proper_embed_complete)
  Index to Qdrant (vector DB)
    ↓ (trigger: indexing_complete)
  Update Redis status → notify via WebSocket
```

### Query Flow

```
User Query → API
  ↓
Check Redis for unfinished tasks?
  ├── Yes → Answer using Redis quick data (partial/in-progress context)
  └── No → RAG Service → Qdrant (vector search)
            → Build context → Return comprehensive answer
```

### Client Interaction

```
External AI Agent (OpenCLAW)
        ↓ REST API + WebSocket
    FastAPI Server
        ↓ (event-driven orchestration)
    Celery Workers
        ↓
    Redis (hot/quick) + Qdrant (vector) + brain/ (filesystem)
```

## Event-Driven Orchestration

The pipeline is triggered by user status events. Events flow through states:

```
[start] → [processing] → [success]
              ↓
          [error] → [retry] → [processing]
```

### Pipeline Orchestration States

| State        | Description                                 | Action                                            |
| ------------ | ------------------------------------------- | ------------------------------------------------- |
| `start`      | File saved successfully                     | Trigger quick embedding + launch async pipeline   |
| `processing` | OCR / translation / embedding in progress   | Update Redis status, push WS progress             |
| `error`      | Task failure (OCR/translation/embed failed) | Log error, retry up to N times, notify client     |
| `retry`      | Re-attempting failed step                   | Resume from failed task, update status            |
| `success`    | All tasks complete                          | Index to Qdrant, update Redis, push WS completion |

### Event Names (TBD)

User-status events that trigger pipeline stages will be defined in a future iteration. Placeholder categories:

- `document_uploaded` — Triggers save + quick embed
- `document_processing` — Emitted during async pipeline
- `document_ready` — Emitted when full pipeline succeeds
- `document_failed` — Emitted on final retry exhaustion

## Memory Architecture

| Memory Type  | Storage                              | Purpose                                                              |
| ------------ | ------------------------------------ | -------------------------------------------------------------------- |
| Hot/Temporal | Redis                                | Quick embeddings, session data, task status, unfinished task context |
| Vector       | Qdrant                               | Dense semantic embeddings for retrieval                              |
| Filesystem   | `brain/english/` + `brain/japanese/` | Original and translated document storage                             |

## Folder Structure

```
memory-rag/
├── app/                      # Main application package
│   ├── api/                  # FastAPI routes and endpoints
│   │   ├── routes/
│   │   │   ├── documents.py  # Document upload, status, retrieval
│   │   │   ├── query.py      # RAG query endpoints
│   │   │   └── health.py     # Health check endpoints
│   │   └── dependencies/     # FastAPI dependency injection
│   ├── models/               # Pydantic schemas
│   │   ├── document.py       # Document request/response models
│   │   ├── query.py          # Query request/response models
│   │   └── response.py       # General response models
│   ├── services/             # Core business logic (pure Python)
│   │   ├── ocr/              # GLM OCR integration
│   │   ├── translation/      # Translation service
│   │   ├── embedding/        # BGE-M3 embedding service
│   │   ├── vector_store/     # Qdrant client wrapper
│   │   ├── redis_client/     # Redis client wrapper
│   │   ├── rag/              # RAG retrieval and answer generation
│   │   └── storage/
│   │       └── filesystem.py  # brain/ folder handler
│   └── core/                 # Configuration, logging, constants
├── workers/                  # Celery async workers
│   ├── tasks/
│   │   ├── save_file.py      # File storage + language detection + dual save
│   │   ├── ocr_task.py       # OCR processing task
│   │   ├── translate_task.py # Translation task
│   │   ├── quick_embed_task.py  # Quick embedding → Redis
│   │   └── embed_task.py     # Proper embedding → Qdrant
│   ├── celery_app.py         # Celery configuration
│   └── worker.py             # Worker entry point
├── brain/                    # Bilingual document storage
│   ├── english/              # English documents
│   └── japanese/             # Japanese documents
├── storage/                  # Local file storage
│   └── uploads/              # Temporary upload staging
├── tests/                    # Test suite
│   ├── unit/                 # Unit tests
│   └── integration/          # Integration tests
├── scripts/                  # Utility and maintenance scripts
├── pyproject.toml            # Project metadata and dependencies
├── docker-compose.yml        # Docker compose configuration
├── Dockerfile                # Container build configuration
├── README.md                 # Project overview
├── PROJECT.md                # This file
└── .env.example              # Environment variables template
```

## Component Responsibilities

### `app/api/`

FastAPI HTTP/WebSocket layer. Handles incoming requests, validates input, returns responses. Dispatches long-running tasks to Celery workers. Manages WebSocket connections for real-time pipeline status updates.

**Files:**

- `routes/documents.py` - Document upload (`POST /documents`), status (`GET /documents/{id}`), language detection, dual file creation
- `routes/query.py` - RAG query (`POST /query`) with Redis fallback for unfinished tasks
- `routes/health.py` - Health check (`GET /`, `GET /health`)
- `routes/ws.py` - WebSocket endpoint for real-time orchestration events

### `app/models/`

Pydantic schemas for request/response validation. Ensures type safety across the API.

**Files:**

- `document.py` - DocumentUploadResponse, DocumentStatusResponse, DocumentInfo
- `query.py` - QueryRequest, QueryResponse, SourceDocument
- `response.py` - General response models
- `events.py` - Event payload schemas for WebSocket messages

### `app/services/`

Pure business logic with no framework dependencies. Each service is self-contained and testable.

| Service                 | Responsibility                                                                    |
| ----------------------- | --------------------------------------------------------------------------------- |
| `ocr/`                  | GLM OCR text extraction from documents                                            |
| `translation/`          | Document translation (EN ↔ JA)                                                    |
| `embedding/`            | BGE-M3 embedding generation (quick + proper)                                      |
| `vector_store/`         | Qdrant CRUD operations (index, search, delete)                                    |
| `redis_client/`         | Redis operations (quick embeddings, task status, session data)                    |
| `rag/`                  | Retrieval-augmented generation logic; chooses Redis vs Qdrant based on task state |
| `storage/filesystem.py` | `brain/` folder read/write, language detection, dual file placement               |

### `workers/`

Celery tasks for async processing. Each task is a step in the pipeline:

| Task                  | Responsibility                                                               |
| --------------------- | ---------------------------------------------------------------------------- |
| `save_file.py`        | Persist uploaded file, detect language, create both EN/JA copies in `brain/` |
| `quick_embed_task.py` | Generate quick embedding and store in Redis immediately                      |
| `ocr_task.py`         | Extract text via GLM OCR                                                     |
| `translate_task.py`   | Translate text between EN/JA                                                 |
| `embed_task.py`       | Generate proper embeddings and index to Qdrant                               |

**Files:**

- `celery_app.py` - Celery configuration and app initialization
- `worker.py` - Worker entry point

### `app/core/`

Application-wide settings and utilities.

**Files:**

- `config.py` - Settings management (Redis, Qdrant, brain paths, Celery)
- `logging.py` - Logging configuration

## API Endpoints

| Method | Endpoint          | Description                                                                                                               |
| ------ | ----------------- | ------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/`               | Welcome endpoint (Hello World)                                                                                            |
| GET    | `/health`         | Health check                                                                                                              |
| POST   | `/documents`      | Upload a document; detects language, saves to `brain/english/` + `brain/japanese/`, triggers quick embed + async pipeline |
| GET    | `/documents/{id}` | Get document status and pipeline progress                                                                                 |
| POST   | `/query`          | Query with RAG (uses Redis if tasks unfinished, else Qdrant)                                                              |
| WS     | `/ws`             | WebSocket for real-time orchestration events (process start, task progress, completion, errors, ready-for-interaction)    |

## Pipeline Details

### Document Processing Steps

1. **Upload** - User submits document via REST API
2. **save_file** - Detect language, store in `brain/english/` or `brain/japanese/`, create counterpart file via translation, save metadata to Redis
3. **quick_embed_task** - Generate quick embedding immediately after save → store in Redis (hot data)
4. **ocr_task** - GLM OCR extracts text from both EN and JA documents
5. **translate_task** - (if needed) Ensure both language versions are accurate
6. **embed_task** - Generate proper dense embeddings for both EN and JA versions
7. **Index** - Store proper embeddings in Qdrant (vector DB); update Redis status to complete

### Orchestration & Retry Logic

- Each async task (OCR, translate, embed) is monitored by the orchestrator
- On failure: retry up to a configurable limit with exponential backoff
- After final failure: emit `document_failed` event, notify client via WebSocket, keep Redis quick data for partial queries
- On success: emit `document_ready`, notify client that full document interaction is available

### Bilingual Processing

- English input → saved to `brain/english/`, translated copy to `brain/japanese/`, both embedded
- Japanese input → saved to `brain/japanese/`, translated copy to `brain/english/`, both embedded
- Both EN and JA embeddings stored in Qdrant for cross-language search

### Two-Phase Embedding

| Phase  | Trigger                          | Storage | Purpose                                                   |
| ------ | -------------------------------- | ------- | --------------------------------------------------------- |
| Quick  | Immediately after file save      | Redis   | Fast retrieval for user queries while async pipeline runs |
| Proper | After OCR + translation complete | Qdrant  | Dense semantic search for comprehensive RAG answers       |

### Query Handling Strategy

```
User Query
  ↓
Check Redis: any tasks with status != success for this document?
  ├── Yes → Build answer from Redis quick embeddings + notify user that full processing is pending
  └── No  → Query Qdrant (full vector DB) → comprehensive RAG answer
```

### WebSocket Events

Clients connect via WebSocket to receive real-time updates:

| Event                   | Direction       | Payload                                                |
| ----------------------- | --------------- | ------------------------------------------------------ | --- | --------- | --------- |
| `process_start`         | Server → Client | `{ document_id, stage: "save                           | ocr | translate | embed" }` |
| `task_progress`         | Server → Client | `{ document_id, stage, progress_percent }`             |
| `task_failed`           | Server → Client | `{ document_id, stage, error, retry_count }`           |
| `task_complete`         | Server → Client | `{ document_id, stage }`                               |
| `ready_for_interaction` | Server → Client | `{ document_id, message: "Document fully processed" }` |

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

# Brain Storage
BRAIN_PATH=./brain
BRAIN_ENGLISH_PATH=./brain/english
BRAIN_JAPANESE_PATH=./brain/japanese

# Upload Staging
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
