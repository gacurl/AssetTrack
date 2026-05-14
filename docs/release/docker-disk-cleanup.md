# Docker Disk Cleanup for Deployment Builds

## Purpose

Use this guide when Docker builds fail because the host is low on disk space.

Why it matters:

- low Docker disk space can break deployment builds
- cleanup must not remove the persistent SQLite database
- unsafe Docker cleanup can cause data loss

## When to Use This Guide

Use this guide when you see build symptoms such as:

- `no space left on device`
- `write failed`
- `failed to copy`
- `failed to register layer`
- a Dockerfile step failing even though the command itself looks unrelated

Disk exhaustion often appears as a failure in a normal build step because Docker cannot write image layers, caches, or temporary build data.

## Persistence Warning

AssetTrack stores its SQLite database in the persistent Docker data path:

```text
./data:/app/data
```

The database file is:

```text
/app/data/assettrack.db
```

Why it matters:

- the production database must survive container restart
- cleanup must not remove the persistent SQLite data
- destructive volume cleanup can remove persistent data depending on deployment configuration

## Check Docker Disk Usage

Before cleanup, check current Docker disk usage:

```bash
docker system df
```

Review:

- image usage
- build cache usage
- container usage
- whether build cache growth is the likely cause

If disk is already tight before a rebuild, perform the safe cleanup sequence below before starting the deployment build.

## Safe Cleanup Sequence

Run this sequence from the deployment repository directory:

```bash
docker compose down
docker system df
docker builder prune -af
docker image prune -af
docker container prune -f
docker system df
```

What this does:

- `docker compose down`
  stops the running containers without removing the bind-mounted `./data` directory
- first `docker system df`
  shows current usage before cleanup
- `docker builder prune -af`
  removes old build cache
- `docker image prune -af`
  removes unused images
- `docker container prune -f`
  removes stopped containers
- final `docker system df`
  confirms how much space was recovered

Why it matters:

- this sequence reclaims common Docker build waste without deleting the bind-mounted SQLite data path used by AssetTrack

## Dangerous Commands

Do not use these casually:

```bash
docker volume prune
docker compose down -v
```

Why they are dangerous:

- Docker volumes may contain persistent application data in some deployment layouts
- `docker compose down -v` removes Compose-managed volumes
- `docker volume prune` removes unused volumes broadly
- depending on deployment configuration, these commands can remove persistent SQLite data

For AssetTrack, treat both commands as destructive unless you have explicitly confirmed the data location and have a safe backup.

## Recommended Pre-Build Check

Before a deployment rebuild when disk is low:

1. Stop the running stack with `docker compose down`.
2. Check space with `docker system df`.
3. If Docker usage is high, run the safe cleanup sequence.
4. Rebuild using the normal deployment flow.
5. Confirm the application starts and the database is still present.

Why it matters:

- cleanup before rebuilding reduces repeated build failures and avoids panic cleanup during an outage

## Verification After Cleanup

After cleanup and rebuild:

1. Start the app with `./scripts/bootstrap_docker.sh`.
2. Run `docker compose ps`.
3. Open the login page.
4. Confirm the expected database-backed state is still present.

If the app starts as if it has a brand-new database, stop immediately and verify the persistent `./data` directory before doing anything else.

Why it matters:

- an unexpected empty system may indicate persistence was lost or the wrong data path is mounted

## Related Documents

- [Deployment Guide](deployment.md)
- [Backup and Restore Runbook](../operations/backup_restore.md)
