# Coolify Dev Testing Deployment

This deployment is a separate Dev Testing environment for the Tauri client. It
uses `docker-compose.coolify.yml`; the local `docker-compose.yml` remains the
hot-reload development stack.

## Server requirements

- Linux server managed by Coolify with Docker Compose support.
- NVIDIA GPU, compatible NVIDIA driver, and NVIDIA Container Toolkit.
- Enough disk space for PostgreSQL, Qdrant, uploaded files, Hugging Face model
  caches, and Ollama models.
- Enough VRAM/RAM for the selected models. The default `qwen3.5:27b` translation
  model may require substantially more memory than the API itself.

Verify GPU access on the server before deployment with `nvidia-smi` and a Docker
NVIDIA runtime test. If the server has no compatible GPU, set the Ollama model
configuration to models suitable for the available hardware and remove the GPU
reservation from the Compose file.

## Coolify application setup

1. Create a Docker Compose application in Coolify connected to this repository.
2. Select the `develop` branch.
3. Set the Compose file to `docker-compose.coolify.yml`.
4. Configure a domain for the `api` service targeting its internal port `8000`.
   Coolify should terminate HTTPS, so the Tauri client uses the resulting
   `https://` URL.
5. Add the environment variables below and deploy.

Coolify must build the application image from the repository. The image already
contains the Python source, `main.py`, `alembic.ini`, and migration package. Do
not add host bind mounts for `./app`, `./workers`, `./main.py`, `./alembic.ini`,
`./alembic`, or the Nginx configuration. Those mounts are intended for local
development and can cause Coolify's file-to-directory mount error.

## Environment variables

Required:

```env
API_KEY=generate-a-long-random-dev-testing-key
POSTGRES_PASSWORD=generate-a-strong-password
```

Recommended values:

```env
CORS_ORIGINS=tauri://localhost,http://tauri.localhost
POSTGRES_USER=memoryrag
POSTGRES_DB=memoryrag
OLLAMA_MODEL_OCR=glm-ocr:latest
OLLAMA_MODEL_FORMAT=qwen3.5:9b
OLLAMA_MODEL_TRANSLATION=qwen3.5:27b
OLLAMA_MODEL_CLEANER=qwen3.5:9b
OLLAMA_MODEL_EMBEDDING=bge-m3
OLLAMA_MODEL_AGENT=qwen3.5:9b
OLLAMA_TIMEOUT=600
EMBEDDING_DEVICE=cpu
```

Coolify should generate and store `API_KEY` and `POSTGRES_PASSWORD` as secrets.
The API key is sent as `X-API-Key` on REST requests. For the document status
WebSocket, send the key as `X-API-Key` when supported by the client or as the
query parameter `api_key`:

```text
wss://<coolify-domain>/api/v1/documents/<document-id>/ws?api_key=<API_KEY>
```

The key is appropriate for Dev Testing access control, but a key embedded in a
Tauri application can be extracted. It is not production user authentication.

## Startup and persistence

Startup is ordered as follows:

1. PostgreSQL, Redis, Qdrant, and Ollama become healthy.
2. `migrate` runs `alembic upgrade head` from the image contents.
3. `ollama-init` pulls each configured model into the persistent Ollama volume.
4. The API and worker start.

The first deployment can take a long time while Ollama downloads models. Check
the `ollama-init`, `migrate`, `api`, and `worker` logs in Coolify. Successful
one-shot services should show an exited-successfully state; API health is
available at `/health`.

The Compose file uses named volumes for PostgreSQL, Qdrant, Ollama models,
brain data, uploaded storage, temporary processing data, and model cache. Keep
these volumes when redeploying. Back them up according to the server's storage
policy before deleting the application or removing volumes.

Only the API is exposed through Coolify. PostgreSQL, Redis, Qdrant, and Ollama
do not publish host ports.

## Tauri configuration

Use the Coolify HTTPS domain as the Dev Testing API base URL:

```text
REST:      https://<coolify-domain>
WebSocket: wss://<coolify-domain>/api/v1/documents/<document-id>/ws?api_key=<API_KEY>
```

Include `X-API-Key: <API_KEY>` on REST requests. If the Tauri client runs with a
different origin, add that exact origin to `CORS_ORIGINS` and redeploy.

## Validation checklist

- Coolify deployment uses `docker-compose.coolify.yml` from `develop`.
- Compose configuration has no unset-variable warnings and no repository bind
  mounts.
- `migrate` completes successfully.
- `ollama-init` completes and `ollama list` shows the configured models.
- `/health` returns `200` without authentication.
- Protected REST requests return `401` without a valid API key and succeed with
  the configured key.
- WebSocket connections reject invalid keys with close code `1008`.
- Upload, document processing, progress notifications, chat, and workspace
  operations work through the HTTPS domain.
- Re-deploying preserves database, Qdrant, Ollama, brain, and uploaded data.
- The existing local Compose stack still starts with reload and local mounts.
