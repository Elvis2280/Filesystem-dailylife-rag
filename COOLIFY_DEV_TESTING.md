# Coolify Dev Testing Deployment

This deployment is a separate Dev Testing environment for the Tauri client. It
uses `docker-compose.coolify.yml`; the local `docker-compose.yml` remains the
hot-reload development stack.

## Server requirements

- Linux server managed by Coolify with Docker Compose support.
- Ollama installed and running directly on the same server as Coolify.
- Enough disk space for PostgreSQL, Qdrant, uploaded files, Hugging Face model
  caches, and the host Ollama models.
- Enough VRAM/RAM for the models already installed in host Ollama. The default
  `qwen3.5:27b` translation model may require substantially more memory than the
  API itself.

The Coolify Compose file does not request an NVIDIA device and does not start a
second Ollama container. GPU support is managed by the host Ollama installation.

## Coolify application setup

1. Create a Docker Compose application in Coolify connected to this repository.
2. Select the `develop` branch.
3. Set the Compose file to `docker-compose.coolify.yml`.
4. Configure a domain for the `api` service targeting its internal port `8000`.
   Coolify should terminate HTTPS, so the Tauri client uses the resulting
   `https://` URL.
5. Configure host Ollama as described below.
6. Add the environment variables below and deploy.

Coolify must build the application image from the repository. The image already
contains the Python source, `main.py`, `alembic.ini`, and migration package. Do
not add host bind mounts for `./app`, `./workers`, `./main.py`, `./alembic.ini`,
`./alembic`, or the Nginx configuration. Those mounts are intended for local
development and can cause Coolify's file-to-directory mount error.

## Configure host Ollama

Ollama normally listens only on `127.0.0.1`. Configure the Linux service to
listen on the Docker-reachable interface:

```bash
sudo systemctl edit ollama.service
```

Add:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

Apply the change:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
sudo ss -ltnp | grep 11434
ollama list
```

Keep port `11434` private. Allow access from the Docker bridge/Coolify network
and deny public internet access with the host firewall. Do not expose Ollama as
a Coolify public domain. The Compose stack maps
`host.docker.internal` to the Docker host using `host-gateway`.

If the host uses a nonstandard address or Docker gateway, set `OLLAMA_HOST` in
Coolify to the reachable host name or IP. Do not use `localhost` or
`127.0.0.1`, because those refer to the API/worker container itself.

Before deploying, verify the endpoint from a container on the server:

```bash
docker run --rm \
  --add-host host.docker.internal:host-gateway \
  curlimages/curl:latest \
  http://host.docker.internal:11434/api/tags
```

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
# Optional when the host Ollama is not reachable through host.docker.internal
# OLLAMA_HOST=host.docker.internal
# OLLAMA_PORT=11434
```

Coolify should generate and store `API_KEY` and `POSTGRES_PASSWORD` as secrets.
The `OLLAMA_MODEL_*` values must exactly match the model names shown by
`ollama list` on the server. The deployment runs `ollama-check`, which retries
the host endpoint and blocks API/worker startup if a model is missing.
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

1. PostgreSQL, Redis, and Qdrant become healthy.
2. `migrate` runs `alembic upgrade head` from the image contents.
3. `ollama-check` retries the host Ollama endpoint and validates all configured
   model names.
4. The API and worker start.

Check the `ollama-check`, `migrate`, `api`, and `worker` logs in Coolify.
Successful one-shot services should show an exited-successfully state; API
health is available at `/health`.

The Compose file uses named volumes for PostgreSQL, Qdrant, brain data, uploaded
storage, temporary processing data, and model cache. Host Ollama owns its model
storage outside this Coolify application. Keep the Compose volumes when
redeploying and back up both those volumes and the host Ollama model directory
according to the server's storage policy.

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
- Compose configuration has no unset-variable warnings, GPU reservations, or
  repository bind mounts.
- `migrate` completes successfully.
- `ollama-check` completes and confirms the configured host Ollama models.
- `/health` returns `200` without authentication.
- Protected REST requests return `401` without a valid API key and succeed with
  the configured key.
- WebSocket connections reject invalid keys with close code `1008`.
- Upload, document processing, progress notifications, chat, and workspace
  operations work through the HTTPS domain.
- Re-deploying preserves database, Qdrant, Ollama, brain, and uploaded data.
- The existing local Compose stack still starts with reload and local mounts.
