#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

exec docker compose exec -T assettrack python -m scripts.import_inventory
