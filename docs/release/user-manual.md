# AssetTrack User Manual

## Who this manual is for

This manual is written for non-technical operators and admins who need to run AssetTrack in day-to-day use.

## Quick Start

1. Start the system with Docker.
2. Open `http://localhost:8000`.
3. Log in with your username and password.
4. Choose the `Issue` or `Return` workflow.
5. Always review the `Preview` page before committing.

## What AssetTrack does

AssetTrack helps you keep track of who has an asset, where the asset belongs, and what changed over time.

In plain language, it lets your team:

- log in
- add assets to the system
- create holders
- issue assets to holders
- return assets back to storage
- manage operator and admin user accounts
- review dashboard counts and drilldowns

AssetTrack is strict on purpose. If a page blocks a commit, it is protecting the audit trail and keeping the asset state consistent.

## Custody is not ownership

AssetTrack records custody, not ownership.

Think of it like a tool room:

- Ownership answers, "Who does this tool belong to?"
- Custody answers, "Who signed it out right now?"

In AssetTrack, an asset can belong to your organization and still be in one person's custody for today's work. The system proves who had custody, when that started, and what action recorded the handoff.

This matters because operators need a clear answer to a simple field question:

"Who is responsible for this item right now?"

That is what AssetTrack is built to show.

## One-off assignment, in plain language

A one-off assignment means you are giving an item to a person or group for a specific job, shift, trip, or task. It does not mean they own it. It means they are the current responsible holder until the item is returned.

Example:

- A laptop is issued to `Taylor` for a site visit.
- Taylor did not buy the laptop.
- Taylor is the current holder until it comes back into storage.

The live operator flow is still the same:

1. Choose the holder and any required prerequisite information.
2. Scan the items into the queue.
3. Review the preview.
4. Confirm the acknowledgment boxes.
5. Commit the handoff.

## What acknowledgment means

Acknowledgment is like signing a hand receipt. It shows that the handoff was reviewed and that responsibility for the handoff was confirmed. It does not mean ownership changed.

In practice, the acknowledgment step means:

- the operator reviewed the batch
- the responsible handoff was confirmed
- the commit can now be recorded in the audit trail

If acknowledgment is missing, AssetTrack blocks the commit on purpose. That protects the record and prevents an incomplete handoff from being saved.

## What "pending email" means

If your local process includes an email or message after a handoff, treat that message as a follow-up notice, not the main record.

The main record is the stored audit event inside AssetTrack.

That means:

- if an email is delayed, the custody record in AssetTrack still stands
- if an email is pending, the system still works
- if there is a question later, use the audit record first

Email can help people stay informed, but email is secondary. AssetTrack is the system of record for who had custody, when, and under what action.

## Before you begin

1. Make sure the system is running.
2. Open `http://localhost:8000`.
3. Have your username and password ready.

## How to log in

1. Open the AssetTrack login page.
2. Enter your username in the `NAME` field.
3. Enter your password in the `PASSWORD` field.
4. Select `LOGIN`.
5. Wait for the dashboard to load.

Expected result:

- You land on the dashboard.
- The top navigation bar becomes available.

## Main navigation

The main navigation uses these labels:

- `Dashboard`
- `Holders`
- `Issue`
- `Return`
- `Preview`
- `Users`
- `Admin Tools`

If you do not see `Users` or `Admin Tools`, your account may not have admin access.

## Issue workflow

Use this workflow when you are giving an asset to a holder.

### Step 1. Open the issue page

1. Select `Issue`.
2. Click once in the scan box.

### Step 2. Scan or enter the asset

1. Scan the asset tag, or type it exactly.
2. Select `Submit`.

Expected result:

- The asset appears in the queue on the page.

### Step 3. Select the holder

1. Open the holder selection link from the issue flow.
2. Search for the correct holder.
3. Select that holder.

Expected result:

- The issue flow shows the selected holder.

### Step 4. Open the preview

1. Select `Open Issue Assets Preview / Confirm`.

Expected result:

- You see the selected holder.
- You see a validation summary.
- You see a per-asset preview of what will change.
- You see the confirmation and acknowledgment section before commit.

### Step 5. Review the preview carefully

1. Confirm the asset tag is correct.
2. Confirm the current state shows the asset in storage.
3. Confirm the after state shows the asset moving to custody under the correct holder.
4. Read any warning or blocked message before continuing.
5. Confirm the holder accepted responsibility for the issue batch.

### Step 6. Commit the issue

1. Check the review confirmation box.
2. Check the responsibility acknowledgment box.
3. Select `Commit Issue`.

Expected result:

- The issue succeeds.
- The asset leaves storage and moves into custody.
- The queue clears after the commit.

## Return workflow

Use this workflow when an issued asset is coming back into storage.

### Step 1. Open the return page

1. Select `Return`.
2. Click once in the scan box.

### Step 2. Scan or enter the asset

1. Scan the returning asset tag, or type it exactly.
2. Select `Submit`.

Expected result:

- The asset appears in the return queue.

### Step 3. Open the return preview

1. Select `Open Return Assets Preview / Confirm`.

Expected result:

- You see the validation summary.
- You see the before and after return state.
- You see the confirmation and acknowledgment section before commit.

### Step 4. Review the return preview

1. Confirm the asset is currently in custody.
2. Confirm the return target slot looks correct.
3. Read any blocked message before continuing.
4. Confirm responsibility for the return handoff was acknowledged before commit.

### Step 5. Commit the return

1. Check the review confirmation box.
2. Check the responsibility acknowledgment box.
3. Select `Commit Return`.

Expected result:

- The return succeeds.
- The asset moves back into storage.
- The queue clears after the commit.

## How to add assets

This is an admin workflow. The named manual `Add Assets` launcher is not shown in normal navigation. Use the approved import workflow or a scoped admin asset-creation path when your local procedure calls for it.

### Step 1. Open the approved asset-creation path

1. Use the import workflow or the scoped admin create form provided by your local process.

### Step 2. Enter the required asset details

1. Enter `asset_tag`.
2. Enter `serial_number`.
3. Enter `manufacturer`.
4. Choose `equipment_type` (`laptop`, `switch`, or `router`).
5. Enter `building`.
6. Enter `room`.

Optional fields:

- `model`
- `model_code`
- `notes`

### Step 3. Decide whether to assign a slot now

1. If you want to assign a slot immediately, check `Assign to slot now?`
2. Enter `case_number`.
3. Enter `slot_number`.

### Step 4. Create the asset

1. Select `Create Asset`.

Expected result:

- The asset is stored in AssetTrack.
- If slot assignment was included, the asset is placed into that slot.

## How to manage holders

Holders are the people or organizations that can receive assets.

### To create a holder

1. Select `Holders`.
2. Select `Add Holder`.
3. Enter the holder name.
4. Select `Create Holder`.

Expected result:

- The new holder is saved and available for issue workflows.

### To find an existing holder

1. Select `Holders`.
2. Search by name or browse the holders list.
3. Open the holder you need.

Use this when you need to confirm the right holder before issuing assets.

## How to manage operators and admin users

This is an admin-only workflow.

### To create a user

1. Select `Users`.
2. In `Create User`, enter a username.
3. Enter a password.
4. Choose the role:
   - `operator` for routine operational use
   - `admin` for administrative control
5. Leave `Active` checked if the user should be able to log in now.
6. Select `Create User`.

Expected result:

- The user appears in the user table.

### To disable or re-enable a user

1. Select `Users`.
2. Find the user in the table.
3. Select `Disable` or `Enable`.

Expected result:

- The `Active` status changes in the table.

### To change a user role

1. Select `Users`.
2. Find the user in the table.
3. Choose the new role in the role dropdown.
4. Select `Set Role`.

Expected result:

- The new role is saved.

### To reset a user password

1. Select `Users`.
2. Find the user in the table.
3. Enter the new password in the password field on that row.
4. Select `Reset Password`.

Expected result:

- The user can log in with the new password.

## How to use the dashboard

1. Select `Dashboard`.
2. Review the summary cards for inventory, slots, custody, and exceptions.
3. Use the dashboard drilldowns if you need more detail.

Use the dashboard to confirm that issue and return actions produced the expected counts.

## Good operating habits

1. Review the preview before every commit.
2. Make sure the correct holder is selected before issuing.
3. Confirm the queue clears after a successful commit.
4. Use the dashboard to verify that the final state looks right.
5. If a page blocks a commit, read the message and fix the cause instead of trying to force the action.

## If something goes wrong

If you have trouble starting the app, logging in, scanning, or confirming persistence, use:

- [Troubleshooting Guide](troubleshooting.md)

For deployment steps, use:

- [Deployment Guide](deployment.md)
