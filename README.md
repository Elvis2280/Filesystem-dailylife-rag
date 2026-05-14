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
│   │   └── rag/             # RAG retrieval and answer generation
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
│   └── uploads/             # Uploaded documents
├── tests/                   # Test suite
│   ├── unit/                # Unit tests
│   └── integration/         # Integration tests
├── scripts/                 # Utility and maintenance scripts
├── pyproject.toml           # Project metadata and dependencies
├── docker-compose.yml       # Docker compose configuration
├── Dockerfile               # Container build configuration
└── README.md                # This file
```

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
3. Configure environment variables (see `.env.example`)
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

### Running with Docker

**Prerequisites:** Docker, Docker Compose, NVIDIA Container Toolkit (for GPU).

```bash
# 1. Create .env from template
cp .env.example .env

# 2. Build and start all services
docker-compose up --build -d
```

**Useful commands:**

| Action | Command |
|--------|---------|
| Check status | `docker-compose ps` |
| View API logs | `docker-compose logs -f api` |
| View worker logs | `docker-compose logs -f worker` |
| View all logs | `docker-compose logs -f` |
| Restart API | `docker-compose restart api` |
| Scale workers | `docker-compose up -d --scale worker=3` |
| Stop everything | `docker-compose down` |
| Stop + remove data | `docker-compose down -v` |
| Shell into API | `docker-compose exec api bash` |
| Verify GPU access | `docker-compose exec worker nvidia-smi` |
| Flower dashboard | Open `http://localhost/flower/` |

**First run:** Workers will download BGE-M3 model (~2GB). Monitor progress with `docker-compose logs -f worker`.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/documents` | Upload a document |
| GET | `/documents/{id}` | Get document status |
| POST | `/query` | Query with RAG |
| GET | `/health` | Health check |

## Development

- Run tests: `pytest`
- Lint: `ruff check .`
- Format: `ruff format .`