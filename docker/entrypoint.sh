#!/bin/sh
set -e

# Fix ownership for bind-mounted and volume-mounted directories
chown -R appuser:appgroup /app/brain /app/storage 2>/dev/null || true

# Create required directory structure (workspace subdirs created on demand)
mkdir -p /app/brain /app/temp_storage /app/temp_storage/ocr

export HOME=/home/appuser

exec gosu appuser "$@"
