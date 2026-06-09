#!/bin/sh
set -e

# Fix ownership for bind-mounted and volume-mounted directories
chown -R appuser:appgroup /app/brain /app/storage 2>/dev/null || true

# Create required directory structure
mkdir -p /app/brain/english/work /app/brain/english/personal \
         /app/brain/japanese/work /app/brain/japanese/personal \
         /app/brain/temp_disabled \
         /app/storage/uploads

export HOME=/home/appuser

exec gosu appuser "$@"
