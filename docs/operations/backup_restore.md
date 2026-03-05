# AssetTrack Backup and Restore Procedure

This runbook defines the manual backup and restore process for AssetTrack SQLite persistence in Docker deployments.

## Database location

- Container DB path: `/app/data/assettrack.db`
- Host path in this repo (via `docker-compose.yml` bind mount): `./data/assettrack.db`
- Config source: `ASSETTRACK_DB_PATH` (commonly set to `/app/data/assettrack.db`)

## Why stop the container first

SQLite is a single-file database. Copying the file while the app is writing can produce an inconsistent backup.  
For reliable backups, stop writes by stopping the container before copying.

## Backup Procedure (manual)

1. Stop the app container:

```bash
docker compose down
```

2. Create a timestamped backup file:

```bash
mkdir -p data/backups
cp data/assettrack.db "data/backups/assettrack-$(date +%Y%m%d-%H%M%S).db"
```

Example backup filename: `assettrack-20260305-091500.db`

3. Start the app again:

```bash
docker compose up -d
```

## Restore Procedure (manual)

1. Stop the app container:

```bash
docker compose down
```

2. Replace the active DB file with a backup:

```bash
cp data/backups/assettrack-YYYYMMDD-HHMMSS.db data/assettrack.db
```

3. Start the app again:

```bash
docker compose up -d
```

## Integrity Verification After Restore

Run a quick schema and data sanity check from the host:

```bash
sqlite3 data/assettrack.db "
SELECT 'holders', COUNT(*) FROM holders
UNION ALL
SELECT 'assets', COUNT(*) FROM assets
UNION ALL
SELECT 'asset_events', COUNT(*) FROM asset_events;
"
```

Optional table list check:

```bash
sqlite3 data/assettrack.db ".tables"
```

## Operational Warnings

- `docker compose down -v` is destructive for container volumes; avoid it during normal backup/restore operations.
- Keep backups outside ephemeral directories and include them in your field backup retention process.
- This procedure is manual by design and does not modify schema or runtime behavior.
