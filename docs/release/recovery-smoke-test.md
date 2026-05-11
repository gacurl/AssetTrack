# Recovery Workflow Smoke Test

Purpose: validate the full in-app recovery workflow before treating it as ready for operators.

Use an incognito browser session.

Preconditions:

- Docker is running
- a valid admin account exists
- at least one known-good backup `.db` file is available
- a queued or failed receipt exists if you want to verify resend/retry blocking against live UI data

## Step 1. Start the system

Run:

```bash
docker compose up -d --build
```

PASS:

- `http://localhost:8000` loads

FAIL:

- stop and fix startup before continuing

## Step 2. Export a fresh backup

1. Log in as admin.
2. Open `Admin Tools`.
3. Select `Download Database Backup`.

PASS:

- browser downloads a non-empty `.db` file

FAIL:

- stop and fix backup export before continuing

## Step 3. Perform restore

1. Stay in `Admin Tools`.
2. Open `Restore Database Backup`.
3. Upload the selected backup file.
4. Select `Validate and Restore`.

PASS:

- restore succeeds
- a success message appears

FAIL:

- stop and investigate validation or replacement failure

## Step 4. Verify recovery mode

1. Return to `Admin Tools`.
2. Review `Recovery State`.

PASS:

- `Status` shows `Active`
- `Acknowledgment` shows `Required`
- restore timestamp is present
- uploaded filename is correct
- rollback artifact path is present

FAIL:

- stop and investigate before operator use

## Step 5. Verify restore history

1. Stay on `Admin Tools`.
2. Review `Restore History`.

PASS:

- a new restore-history row is present
- timestamp is present
- uploaded filename is correct
- rollback artifact is present
- result shows `Success`

FAIL:

- stop and investigate before operator use

## Step 6. Verify resend/retry block

1. Open `Receipts`.
2. Open a queued or failed receipt.
3. Attempt the resend or retry action if one is available.

PASS:

- the receipt page clearly shows resend/retry is blocked during recovery mode
- the send endpoint is blocked while recovery mode is active

FAIL:

- stop and investigate before operator use

## Step 7. Verify restored state

1. Open `Dashboard`.
2. Open the human-readable report.
3. Open `Receipts`.
4. Confirm expected records are present.

PASS:

- pages load normally
- holder, asset, and recent record counts are plausible for the restored backup

FAIL:

- stop and do not acknowledge recovery

## Step 8. Acknowledge recovery

1. Return to `Admin Tools`.
2. Select `Acknowledge Recovery and Resume`.

PASS:

- success message appears
- `Status` changes to `Inactive`
- `Acknowledgment` changes to `Cleared`

FAIL:

- stop and investigate before allowing normal receipt delivery actions

## Step 9. Verify post-acknowledgment behavior

1. Return to the same queued or failed receipt.
2. Confirm the recovery block is gone.
3. Confirm the send route is no longer blocked by recovery mode.

PASS:

- resend/retry is no longer blocked by recovery mode

FAIL:

- stop and investigate acknowledgment handling

## Step 10. Verify workflow seam still works

1. Open `Issue`.
2. Confirm entry loads normally.
3. Open `Return`.
4. Confirm entry loads normally.

PASS:

- core workflow pages still load
- no recovery step redirected the operator around `entry → prerequisite → queue → preview → commit`

FAIL:

- stop and investigate before operator use

## Step 11. Verify no custody-event side effects

Check:

- restore history appears only in admin operational surfaces
- no new custody events were created just because restore ran

PASS:

- recovery remains operational metadata only

FAIL:

- stop immediately and escalate
