# AssetTrack Deployment Guide

## Purpose

This guide explains how to deploy, start, stop, and verify the AssetTrack MVP release using the supported Docker Compose workflow.

AssetTrack runs on macOS, Linux, and Windows as long as Docker is installed.

## Prerequisites

Before starting, make sure you have:

- Git
- Docker Desktop or Docker Engine with Compose support
- Port `8000` available on the local machine

## Clone the repository

From a terminal, run:

```bash
git clone https://github.com/gacurl/AssetTrack.git
cd AssetTrack
```

## Start the system

From the repository root, run:

```bash
./scripts/bootstrap_docker.sh
```

What this does:

1. Builds the AssetTrack Docker image.
2. Ensures the host `./data` bind-mount directory exists.
3. Applies first-run write permissions so the non-root container can create SQLite files.
4. Starts the AssetTrack container in the background.
5. Exposes the application on port `8000`.
6. On first run, initializes the approved SQLite schema in `/app/data/assettrack.db` if the database file is missing or empty.

After startup, open:

- `http://localhost:8000`

If this is a brand-new database with no users yet, bootstrap the first admin at:

- `http://localhost:8000/bootstrap/admin`

## Verify the container is running

Run:

```bash
docker compose ps
```

Expected result:
The `assettrack` container shows status **running**.

## Stop the system

To stop the running system, use:

```bash
docker compose down
```

This stops and removes the running container, but it does not remove the persisted database files in the mounted data path.

## Persistent database location

The application database path inside the container is:

```text
/app/data/assettrack.db
```

AssetTrack persists SQLite data across restarts by keeping the database in the mounted `/app/data` path. In this repository's Docker Compose setup, the host `./data` directory is mounted into `/app/data`, so restarting or rebuilding the container does not delete the database.

This means:

- `docker compose down` does not erase the database
- `./scripts/bootstrap_docker.sh` starts the app again using the same database file
- SQLite persistence survives normal container restarts

## Standard inventory import path

If you need to load the approved `.xlsx` inventory workbook, run the import inside the existing `assettrack` container:

```bash
./scripts/bootstrap_docker.sh
./scripts/import_inventory_docker.sh
```

Equivalent direct command:

```bash
docker compose exec -T assettrack python -m scripts.import_inventory
```

This keeps the import runtime aligned with the Docker image, avoids host Python package drift, and writes into the same mounted `/app/data/assettrack.db` database used by the app.

## Basic deployment verification

After startup:

1. Open `http://localhost:8000`.
2. Confirm the login page appears.
3. Log in with a valid user account.
4. Confirm you are redirected to the dashboard.

## Recommended operating pattern

For normal field use:

1. Start the app with `./scripts/bootstrap_docker.sh`.
2. Perform the required operator workflows.
3. Stop the app with `docker compose down` when finished.

## Related release documents

- [Smoke Test](smoke-test.md)
- [Troubleshooting Guide](troubleshooting.md)
- [User Manual](user-manual.md)
- [Docker Disk Cleanup](docker-disk-cleanup.md)
- [Backup and Restore Runbook](../operations/backup_restore.md)
