#!/bin/sh
set -e

# Fix ownership for bind-mounted and volume-mounted directories
chown -R appuser:appgroup /app/brain /app/storage 2>/dev/null || true

# Create required directory structure
mkdir -p /app/brain/english/work /app/brain/english/personal \
         /app/brain/japanese/work /app/brain/japanese/personal \
         /app/brain/temp_disabled \
         /app/storage/uploads

# Drop privileges and run the actual command
exec gosu appuser "$@"
