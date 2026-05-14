# AssetTrack Backup and Restore Procedure

This runbook defines the approved backup export and in-app restore workflow for AssetTrack SQLite persistence.

## Database location

- container DB path: `/app/data/assettrack.db`
- host path in this repo: `./data/assettrack.db`
- config source: `ASSETTRACK_DB_PATH`

Why it matters:

- this is the live database path
- backup and restore work must preserve this data unless an admin intentionally performs a validated in-app restore
- manual overwrite of this path creates data-loss risk

## Backup cadence

Take a full database backup at these times:

- before each live event
- after each live event
- daily during multi-day events
- before deployment or build changes
- before restore testing
- before any recovery action on a live system

Why it matters:

- AssetTrack is offline-first, so local backup discipline is the recovery plan
- event activity after the last backup cannot be recreated automatically from a later restore

## Backup storage rules

Store backup files:

- outside ephemeral temp directories
- outside Docker cache or container-only paths
- in a controlled operator backup location
- with restricted access appropriate for production custody data

Recommended practice:

- keep at least one recent local backup immediately available
- keep older event-period backups until the event closes cleanly
- label backups clearly enough that an operator can identify the correct restore point under time pressure

## Recovery model

AssetTrack restore is an in-app operational recovery action.

Restore:

- validates the uploaded SQLite file
- preserves the current live DB as a rollback artifact
- replaces the live DB only after validation passes
- activates recovery mode
- records operational restore history

Restore does not:

- create custody events
- change audit history
- merge database snapshots
- silently clear recovery mode

## Safe backup path

Use the in-app export whenever you need a downloadable backup copy before recovery, troubleshooting, or field transport.

Operator steps:

1. Log in as admin.
2. Open `Admin Tools`.
3. Select `Download Database Backup`.
4. Store the downloaded `.db` file in a controlled backup location.

Expected filename pattern:

`assettrack-backup-YYYYMMDD-HHMMSS.db`

Recommended interpretation:

- `YYYYMMDD` is the local calendar date
- `HHMMSS` is the local 24-hour time

Recommended operator notes to record with the file:

- who took the backup
- why it was taken
- whether it was pre-event, post-event, pre-deployment, or pre-restore-test

Why this is safe:

- no schema change occurs
- no runtime behavior changes
- no custody or audit state is modified

## Backup verification

After downloading a backup:

1. Confirm the file name matches the expected `assettrack-backup-YYYYMMDD-HHMMSS.db` pattern.
2. Confirm the file is stored in the intended backup location.
3. Confirm the file is not zero bytes.
4. Record when and why the backup was taken.

If any of those checks fail:

- stop and correct the backup handling before relying on the file

Why it matters:

- a backup that cannot be identified or located is not operationally reliable

## In-app restore path

Use this path when the live database is no longer trusted and you have a known-good backup file.

1. Export one fresh backup first.
2. Log in as admin.
3. Open `Admin Tools`.
4. Select `Restore Database Backup`.
5. Upload the selected backup `.db` file.
6. Select `Validate and Restore`.

Do not:

- overwrite `./data/assettrack.db` manually
- copy a backup file directly over the live DB path
- use restore as a merge tool
- use destructive Docker volume cleanup as part of restore

Expected result:

- restore succeeds
- the current live DB is preserved as a rollback artifact
- recovery mode activates
- restore history records the operation

## Recovery mode expectations

While recovery mode is active:

- admins see a recovery banner
- `Admin Tools` shows recovery metadata
- `Admin Tools` shows restore history
- resend and retry actions for queued receipts are blocked
- core issue and return workflows remain available unless another control blocks them

Recovery mode remains active across restart until an admin explicitly acknowledges it.

## Rollback expectations

After successful restore, expect:

- a rollback artifact path in `Recovery State`
- the rollback artifact path recorded in `Restore History`

Do not expect:

- automatic rollback selection
- automatic rollback cleanup
- automatic reconstruction of missing custody data

## Validation before acknowledgment

Do not acknowledge recovery until all checks pass.

Required checks:

- `PASS` `Recovery State` shows `Status: Active`
- `PASS` `Recovery State` shows `Acknowledgment: Required`
- `PASS` uploaded filename matches the intended restore file
- `PASS` rollback artifact path is present
- `PASS` restore history contains the new restore entry
- `PASS` dashboard loads
- `PASS` human-readable report loads
- `PASS` receipts screens load
- `PASS` resend/retry is visibly blocked during recovery mode
- `PASS` holder / asset / recent record counts are plausible for the selected backup
- `PASS` the restored state matches the expected event history snapshot for the selected backup point

If any check fails:

- stop operator use
- do not acknowledge recovery
- investigate before allowing new work

Why it matters:

- restored operational state must still reconcile with the event history captured in the selected backup

## Clear recovery mode

After validation:

1. Open `Admin Tools`.
2. In `Recovery State`, select `Acknowledge Recovery and Resume`.

Expected result:

- recovery mode clears
- acknowledgment state becomes `Cleared`
- resend/retry blocking lifts

## What not to expect from restore

Do not expect restore to:

- recreate lost work from after the selected backup was taken
- resend queued receipts automatically
- create a custody correction trail
- change workflow order

Restore is a controlled snapshot replacement, not a history repair tool.

## Recovery smoke test

For the full end-to-end procedure, use:

- [Recovery Workflow Smoke Test](../release/recovery-smoke-test.md)
- [Admin Recovery Workflow](../operator/admin-recovery-workflow.md)
- [Admin Database Backup Export](../operator/admin-backup-export.md)
- [Deployment Guide](../release/deployment.md)
- [Docker Disk Cleanup](../release/docker-disk-cleanup.md)

## Operational warnings

- `docker compose down -v` remains destructive and is not part of normal recovery.
- `docker volume prune` remains destructive and is not part of normal recovery.
- `rm -f data/assettrack.db` remains destructive and belongs only to explicit reset workflows.
- manually replacing `./data/assettrack.db` is destructive and is not an approved restore path.
- Keep backups outside ephemeral directories.
- Restore history is operational metadata only. It does not replace custody or audit history.
