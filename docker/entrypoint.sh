#!/bin/sh
set -e

# Fix ownership for runtime write directories and source code bind mount
chown -R appuser:appgroup /app/brain /app/storage /app/temp_storage 2>/dev/null || true

# Create required directory structure (workspace subdirs created on demand)
mkdir -p /app/brain /app/temp_storage /app/temp_storage/ocr

export HOME=/home/appuser

exec gosu appuser "$@"
