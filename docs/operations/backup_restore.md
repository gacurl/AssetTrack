# AssetTrack Backup and Restore Procedure

This runbook defines the manual backup and restore process for AssetTrack SQLite persistence in Docker deployments.

## Database location

- Container DB path: `/app/data/assettrack.db`
- Host path in this repo (via `docker-compose.yml` bind mount): `./data/assettrack.db`
- Config source: `ASSETTRACK_DB_PATH` (commonly set to `/app/data/assettrack.db`)

## Why stop the container first

SQLite is a single-file database. Copying the file while the app is writing can produce an inconsistent backup.  
For reliable backups, stop writes by stopping the container before copying.

## Safe Backup Procedure

Use this path for routine protection before upgrades, troubleshooting, or field transport.

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

Why this is safe:

- `docker compose down` stops writes but preserves the mounted `./data/assettrack.db` file
- the backup is a point-in-time copy of the real host-mounted database
- no schema or runtime behavior changes occur

## Normal Restore Procedure

Use this path when you want to restore a known-good backup while preserving the current damaged database file for investigation.

1. Stop the app container:

```bash
docker compose down
```

2. Preserve the current DB before replacing it:

```bash
mkdir -p data/backups
mv data/assettrack.db "data/backups/pre-restore-$(date +%Y%m%d-%H%M%S).db"
```

3. Replace the active DB file with the selected backup:

```bash
cp data/backups/assettrack-YYYYMMDD-HHMMSS.db data/assettrack.db
```

4. Start the app again:

```bash
docker compose up -d
```

This is the preferred restore path because it keeps the pre-restore file available for rollback or forensic review.

## Destructive Reset Path

Use this only when you intentionally want to discard the current local database and start from an empty file.

```bash
docker compose down
rm -f data/assettrack.db
./scripts/bootstrap_docker.sh
```

Warnings:

- this does not restore prior custody history
- on next start, AssetTrack initializes a fresh approved schema if no DB file exists
- only use this when a reset is explicitly intended

## Verification After Restore

Run these checks before allowing operators back into the system.

1. Confirm the restored file exists at the expected host path:

```bash
ls -l data/assettrack.db
```

2. Run a quick schema and data sanity check from the host:

```bash
sqlite3 data/assettrack.db "
SELECT 'holders', COUNT(*) FROM holders
UNION ALL
SELECT 'assets', COUNT(*) FROM assets
UNION ALL
SELECT 'asset_events', COUNT(*) FROM asset_events;
"
```

3. Run SQLite integrity check:

```bash
sqlite3 data/assettrack.db "PRAGMA integrity_check;"
```

4. Optional table list check:

```bash
sqlite3 data/assettrack.db ".tables"
```

5. Start the app and confirm the expected login/dashboard behavior:

```bash
docker compose up -d
docker compose ps
```

Operational confirmation:

- login page loads on `http://localhost:8000`
- expected holder / asset / event counts are present
- recent known records appear as expected
- no operator starts new work until restore verification is complete

## Operational Warnings

- `docker compose down -v` is destructive for container volumes; avoid it during normal backup/restore operations.
- `rm -f data/assettrack.db` is destructive and belongs only to the explicit reset path above.
- Keep backups outside ephemeral directories and include them in your field backup retention process.
- Restore replaces the active SQLite file. Treat it as a recovery operation, not normal workflow.
- AssetTrack remains append-only at the event level, but restoring an older backup reverts the entire database snapshot to that earlier point in time.
- This procedure is manual by design and does not modify schema or runtime behavior.
