# Admin Recovery Workflow

Use this procedure when you need to replace the live SQLite database with a known-good backup.

This is an operational recovery action.

It is not:

- a custody workflow
- a receipt workflow
- an audit correction workflow

## When to use restore

Use restore when the live database is no longer trusted and you have a known-good backup file.

Examples:

- the live DB is damaged
- the live DB was replaced accidentally
- the system starts but known-good records are missing or corrupted
- you must roll back to an earlier operational snapshot

Do not use restore for:

- normal issue or return work
- correcting one holder or one asset
- resending one receipt
- changing custody history

## What restore does

Restore:

- validates the uploaded SQLite file before replacing anything
- preserves the current live DB as a rollback artifact first
- replaces the live DB only after validation passes
- activates recovery mode
- records a restore-history entry

## What restore does not do

Restore does not:

- create custody events
- append audit events
- merge databases
- replay missing records
- automatically clear recovery mode
- automatically resend or retry queued receipts

## Backup export first

Before restore:

1. Log in as an admin.
2. Open `Admin Tools`.
3. Select `Download Database Backup`.
4. Save the downloaded `.db` file in a controlled backup location.

Why this matters:

- you keep one more rollback point
- you preserve the exact pre-restore live state

## In-app restore procedure

1. Log in as an admin.
2. Open `Admin Tools`.
3. Select `Restore Database Backup`.
4. Choose the known-good backup `.db` file.
5. Select `Validate and Restore`.

Expected result:

- restore succeeds
- the current DB is preserved as a rollback artifact
- recovery mode becomes active

## Recovery mode means

Recovery mode means the restored database is live but not yet operator-validated.

While recovery mode is active:

- admins see a recovery banner
- admins see restore metadata on `Admin Tools`
- restore history is visible on `Admin Tools`
- receipt resend and retry actions are blocked
- normal issue and return workflows remain available unless another control blocks them

## Acknowledgment means

Acknowledgment means:

- an admin reviewed the restored system
- the admin accepts the restored state for normal operations
- recovery mode can clear

Acknowledgment does not mean:

- a new backup was created
- lost data was recreated
- receipt delivery was retried automatically

## What to verify before acknowledgment

Do these checks in order:

1. Open `Admin Tools`.
2. Confirm `Recovery State` shows:
   - `Status: Active`
   - `Acknowledgment: Required`
3. Confirm the uploaded filename is the file you intended to restore.
4. Confirm the rollback artifact path is present.
5. Confirm `Restore History` contains the new restore entry.
6. Open the human-readable report and check expected records.
7. Open the dashboard and confirm the system loads normally.
8. Open `Receipts` and confirm receipt screens load.
9. Open one queued or failed receipt and confirm resend/retry is visibly blocked.
10. Verify expected holder, asset, and recent record counts look plausible for the selected backup.

## Acknowledge and resume

Only after the checks above pass:

1. Return to `Admin Tools`.
2. In `Recovery State`, select `Acknowledge Recovery and Resume`.

Expected result:

- recovery mode clears
- acknowledgment state becomes `Cleared`
- receipt resend and retry actions can resume

## Rollback expectations

AssetTrack preserves the pre-restore live DB before replacement.

Expect:

- one rollback artifact path in `Recovery State`
- the rollback artifact name shown in restore history
- the rollback artifact to remain operational metadata only

Do not expect:

- automatic rollback selection
- automatic rollback cleanup
- automatic comparison between snapshots

## Restore history means

Restore history is an operational record.

It is informational only.

It helps answer:

- when restore happened
- which file was used
- which rollback artifact was created
- whether the current active restore still needs acknowledgment

It does not:

- replace audit history
- replace receipts
- replace custody events

## Under pressure

Use this short sequence:

1. Export backup.
2. Restore known-good DB.
3. Check recovery state.
4. Check rollback artifact.
5. Check restore history.
6. Check report, dashboard, receipts.
7. Confirm resend/retry block.
8. Acknowledge only after validation.
