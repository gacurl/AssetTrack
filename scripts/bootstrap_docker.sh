#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

DATA_DIR="data"

echo "Ensuring ${DATA_DIR}/ exists for Docker bind mount..."
mkdir -p "$DATA_DIR"

echo "Setting ${DATA_DIR}/ permissions for first-run SQLite creation..."
chmod 0777 "$DATA_DIR"

if [ ! -w "$DATA_DIR" ]; then
    echo "AssetTrack bootstrap failed: ${DATA_DIR}/ is not writable." >&2
    exit 1
fi

echo "Starting AssetTrack with Docker Compose..."
exec docker compose up -d --build
