# AssetTrack Smoke Test

## Purpose

This smoke test is a short, reproducible release check for the Dockerized MVP. It confirms the system starts, accepts login, supports core admin setup, processes one issue, processes one return, clears the queue, and updates the dashboard.

## Test data to use

Use sample values like these so the test is easy to repeat:

- Operator username: `operator-smoke`
- Operator password: `operator-pass-123`
- Holder name: `Smoke Holder`
- Asset tag: `SMOKE-0001`
- Serial number: `SER-SMOKE-0001`
- Manufacturer (optional): `SmokeTech`
- Equipment type: `laptop`
- Building: `HQ`
- Room: `101`
- Case number: `CASE-1`
- Slot number: `A-01`

## Preconditions

- Docker is running
- The repository is cloned locally
- You have an admin account available

## Steps

### 1. Start system

Run:

```bash
docker compose up -d --build
```

Expected result:

- The container builds and starts successfully.
- `http://localhost:8000` becomes reachable.

If this step fails, stop the test and check `troubleshooting.md`.

### 2. Login

1. Open `http://localhost:8000`.
2. Enter valid credentials.
3. Select `LOGIN`.

Expected result:

- Login succeeds.
- You are redirected to the dashboard.

If this step fails, stop the test and check `troubleshooting.md`.

### 3. Add operator

1. Select `Users`.
2. In `Create User`, enter the sample operator username and password.
3. Leave `Role` set to `operator`.
4. Leave `Active` checked.
5. Select `Create User`.

Expected result:

- The new operator appears in the user table.

If this step fails, stop the test and check `troubleshooting.md`.

### 4. Add holder

1. Select `Holders`.
2. Select `Add Holder`.
3. Enter `Smoke Holder`.
4. Select `Create Holder`.

Expected result:

- The holder is created successfully.
- The holder can be found in the holders screens.

If this step fails, stop the test and check `troubleshooting.md`.

### 5. Add asset

1. Select `Add Assets`.
2. Enter:
   - `asset_tag`: `SMOKE-0001`
   - `serial_number`: `SER-SMOKE-0001`
   - `manufacturer`: `SmokeTech`
   - `equipment_type`: `laptop`
   - `building`: `HQ`
   - `room`: `101`
3. Check `Assign to slot now?`
4. Enter:
   - `case_number`: `CASE-1`
   - `slot_number`: `A-01`
5. Select `Create Asset`.

Expected result:

- The asset is created successfully.
- The asset is available for later issue.

If this step fails, stop the test and check `troubleshooting.md`.

### 6. Issue asset

1. Select `Issue`.
2. Click in the scan box and scan or type `SMOKE-0001`.
3. Select `Submit`.
4. Open the holder selector and choose `Smoke Holder`.

Expected result:

- The asset appears in the issue queue.
- The selected holder is shown for the pending issue batch.

If this step fails, stop the test and check `troubleshooting.md`.

### 7. Preview

1. Select `Open Issue Assets Preview / Confirm`.

Expected result:

- The preview page shows the selected holder.
- The validation summary shows the batch as ready.
- The per-asset diff shows the asset moving from storage to custody.

If this step fails, stop the test and check `troubleshooting.md`.

### 8. Commit

1. Check the confirmation box.
2. Select `Commit Issue`.

Expected result:

- The issue succeeds.
- The queue is cleared.
- The holder selection is cleared.

If this step fails, stop the test and check `troubleshooting.md`.

### 9. Return asset

1. Select `Return`.
2. Click in the scan box and scan or type `SMOKE-0001`.
3. Select `Submit`.
4. Select `Open Return Assets Preview / Confirm`.
5. Check the return confirmation box.
6. Select `Commit Return`.

Expected result:

- The return succeeds.
- The asset moves back to storage.

If this step fails, stop the test and check `troubleshooting.md`.

### 10. Verify queue clears

1. Stay on the return workflow after commit.
2. Confirm the queue count is zero.

Expected result:

- No stale queued asset remains after the return commit.

If this step fails, stop the test and check `troubleshooting.md`.

### 11. Verify dashboard updates

1. Select `Dashboard`.
2. Review the summary panels.
3. Open holder and case drilldowns if needed.

Expected result:

- The returned asset is no longer listed as in custody.
- Inventory and custody counts reflect the completed issue and return.
- Slot occupancy is consistent again after the return.

If this step fails, stop the test and check `troubleshooting.md`.

## Cleanup

When the test is complete, stop the system:

```bash
docker compose down
```

## Related documents

- [Deployment Guide](deployment.md)
- [User Manual](user-manual.md)
- [Troubleshooting Guide](troubleshooting.md)
- [Recovery Workflow Smoke Test](recovery-smoke-test.md)
