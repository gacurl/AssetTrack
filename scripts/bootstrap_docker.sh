#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

DATA_DIR="data"

echo "Starting AssetTrack with Docker Compose..."
echo "Docker Compose will initialize ${DATA_DIR}/ ownership for the non-root AssetTrack user."

exec docker compose up -d --build
