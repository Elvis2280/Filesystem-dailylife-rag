FROM nvidia/cuda:12.8.0-runtime-ubuntu24.04

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3-pip \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python3.12 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser \
    && chown -R appuser:appgroup /app

USER appuser

COPY --chown=appuser:appgroup . .

RUN mkdir -p /app/brain/english /app/brain/japanese /app/storage/uploads

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
