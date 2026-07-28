# AssetTrack Operator User Manual

AssetTrack records who has each asset and where each asset is stored.

Use this manual for daily work with laptops, switches, and routers.

## Safety Rules

Read these rules first.

- AssetTrack history is append-only. New actions add new history.
- Do not edit or delete old history.
- Email does not create custody. Only an Issue or Return commit creates custody history.
- Corrections are not for normal work. Use Issue and Return for normal handoffs.
- Do not use destructive Docker volume commands.
- Do not run `docker compose down -v`.
- Do not run `docker volume prune`.
- Do not run `docker system prune --volumes`.
- Back up the database before restore.
- Recovery mode requires review and admin acknowledgment before normal email delivery resumes.

Why it matters: these rules protect the custody record.

## Start And Log In

1. Start AssetTrack with the approved Docker start command for your site.
2. Open `http://localhost:8000`.
3. Enter your user name.
4. Enter your password.
5. Select `LOGIN`.

Expected result:

- The Dashboard opens.
- The top navigation appears.

## Main Navigation

The main navigation shows:

- `Dashboard`
- `Issue`
- `Return`
- `Assets`
- `Holders`
- `Reports`

Admins also see the `Admin` menu.

The `Admin` menu can include:

- `Admin Tools`
- `Users`
- `Reference Data`
- `Import Holders`
- `Operational Report`
- `Restore Database`

## Dashboard

Use the Dashboard for a quick view of the system.

The Dashboard shows:

- assets out
- assets remaining
- total assets
- current custody
- case status
- asset search
- custody map
- problems

Use Dashboard links to open the matching work area.

## Find An Asset

Use this when you need to know where an asset is now.

1. Select `Assets`.
2. Enter or scan the asset tag.
3. Select `Search`.

If AssetTrack finds the asset, it shows:

- asset tag
- asset type
- current status
- holder, if the asset is issued
- building and room, if recorded
- case and slot, if recorded
- history link

If AssetTrack does not find the asset, check the tag and search again.

## Issue A Laptop

Use Issue when you give a laptop to a holder.

1. Select `Issue`.
2. Select the correct holder.
3. Enter the current building and room if the page asks for it.
4. Scan or type the laptop asset tag.
5. Confirm the laptop appears in the queue.
6. Select the Issue preview button.
7. Review the holder, asset tag, and warnings.
8. Check the review box.
9. Check the responsibility acknowledgment box.
10. Select `Commit Issue`.

Expected result:

- The laptop moves from storage to the holder.
- AssetTrack creates custody history.
- AssetTrack creates a receipt record.
- The queue clears.

Stop if the preview is blocked. Read the message and fix the problem before commit.

## Return A Laptop

Use Return when a holder gives a laptop back to storage.

1. Select `Return`.
2. Scan or type the laptop asset tag.
3. Confirm the laptop appears in the return queue.
4. Select the Return preview button.
5. Review the current holder and return destination.
6. Check the review box.
7. Check the responsibility acknowledgment box.
8. Select `Commit Return`.

Expected result:

- The laptop moves back to storage.
- AssetTrack creates custody history.
- AssetTrack creates a receipt record.
- The queue clears.

Stop if the preview is blocked. Read the message and fix the problem before commit.

## Locate Switches And Routers

Use Asset Search to locate a switch or router.

1. Select `Assets`.
2. Enter or scan the switch or router asset tag.
3. Select `Search`.
4. Review the case and slot.

Switches and routers can appear in case storage. AssetTrack shows their asset tag, type, status, case, and slot when those values are recorded.

## Move A Switch Or Router To Another Slot

**Admin only**

Use this only to move a stored switch or router from one slot to another.

1. Select `Admin`.
2. Select `Admin Tools`.
3. Select `Move Slot`.
4. Select the occupied source slot.
5. Select an empty destination slot.
6. Review the move preview.
7. Confirm the source case and slot.
8. Confirm the destination case and slot.
9. Select `Confirm Move`.

Expected result:

- The asset moves to the new slot.
- Custody does not change.
- No custody receipt is created.

Why it matters: a slot move records storage logistics. It does not hand the asset to a person.

## Case Status

Use Case Status when you need to inspect case storage.

1. Open the Dashboard.
2. Select the Case Status area.
3. Choose a case.
4. Review the slots and assets.

Use this before moving a switch or router so you know the current slot.

## Printable Case Inventory

Use Case Inventory when you need a printable list for one case.

1. Select `Reports`.
2. Select `Case inventory`.
3. Choose a case or enter a case number.
4. Select `Preview Inventory`.
5. Review the case number, generated date, and asset count.
6. Review each asset tag, type, description or model, and slot.
7. Select `Print` to print from the browser.
8. Select `Download PDF` to save a PDF.

If the case is empty, AssetTrack shows no assets for that case.

If the case number is invalid, AssetTrack shows that the case was not found.

## Holders

Use Holders to find people or groups that can receive assets.

1. Select `Holders`.
2. Search by holder name or other shown details.
3. Open the holder you need.
4. Review the holder details before issuing an asset.

## Reports

Use Reports to review current system state.

Reports can show:

- asset counts
- assets
- holders
- current custody
- recent events
- location and case data
- receipt search
- case inventory

Reports are read-only for normal operators.

## Receipts

AssetTrack creates receipt records when Issue or Return commits.

Use receipts to review or download handoff records.

1. Select `Reports`.
2. Select the receipt search link.
3. Search by asset tag, holder name, building, or room.
4. Open the receipt.
5. Select `Download Receipt PDF` if you need a PDF copy.

### Email Boundaries

Email is a notice only.

- Email does not create custody.
- Email does not reverse custody.
- Email does not change custody.
- If email fails, the custody record still stands.
- Retry and resend only send receipt email.

### Send Or Retry Receipt Email

Use this when a receipt is pending or failed.

1. Open the receipt.
2. Select `Send Initial Receipt Email` or `Retry Failed Delivery`.
3. Review the result message.

Expected result:

- AssetTrack sends or retries the email.
- Custody history does not change.

### Resend Delivered Receipt Email

**Admin only**

Use this when a delivered receipt must be sent again.

1. Open the delivered receipt.
2. Select `Resend Delivered Receipt`.
3. Review the result message.

Expected result:

- AssetTrack sends another copy of the receipt email.
- Custody history does not change.

## Admin Tools

**Admin only**

Use Admin Tools for setup and controlled maintenance.

Admin Tools can include:

- manage users
- manage reference data
- import holders
- create or edit assets
- import assets from CSV or XLSX
- provision, assign, or move slots
- receipt search
- receipt CC settings
- database backup
- database restore
- corrections

Do not use corrections for normal Issue, Return, or slot-move work.

## Users

**Admin only**

Use Users to manage who can log in and what role they have.

1. Select `Admin`.
2. Select `Users`.
3. Review the user list.
4. Use the page controls for approved user changes.

Do not share user accounts.

## Reference Data

**Admin only**

Use Reference Data to manage local lists such as organizations and buildings.

1. Select `Admin`.
2. Select `Reference Data`.
3. Review the current values.
4. Add or update values only when approved by your site process.

Why it matters: clean reference data helps operators select the right holder and location.

## Import Holders

**Admin only**

Use Import Holders when you need to load holder records from an approved file.

1. Select `Admin`.
2. Select `Import Holders`.
3. Choose the holder import file.
4. Select `Preview Holders`.
5. Review the totals, blocked rows, and proposed before/after changes.
6. Select `Confirm and Commit Holder Import` only after the preview is correct.
7. Review the result.

Fix the file if AssetTrack reports duplicate, ambiguous, invalid, or blocked rows. Preview does not create or update Holders or Organizations. Confirmed imports currently change Holder and Organization reference data only; they do not create custody events or a separate persistent audit record. Persistent reference-data import auditing is deferred to Issue 30-27 / #1078.
## Import Assets

**Admin only**

Use Import Assets for supported bulk asset imports.

Supported files:

- CSV
- XLSX

Supported asset types:

- Laptop
- Switch
- Router

1. Select `Admin`.
2. Select `Admin Tools`.
3. Select `Import Assets`.
4. Choose the CSV or XLSX file.
5. Select `Analyze Import`.
6. Review the preview.
7. Fix blocked rows before import, or leave them blocked.
8. Confirm the preview.
9. Commit the approved rows.
10. Review the results.

Expected result:

- Analyze Import creates a preview only. It does not write assets, events, slots, or occupancy.
- Commit requires explicit confirmation.
- Approved safe rows commit atomically.
- Blocked rows do not modify state.
- The results show category totals and committed row counts.

Legacy network CSV command-line utilities are not normal operator procedures. They are retained for internal or maintainer use only.

## Backup The Database

**Admin only**

Create a backup before restore or other high-risk maintenance.

1. Select `Admin`.
2. Select `Admin Tools`.
3. Select `Download DB Backup`.
4. Save the backup in your approved backup location.
5. Confirm the file was saved.

Do not overwrite `data/assettrack.db` by hand.

## Restore The Database

**Admin only**

Use restore only for recovery.

Before restore:

1. Stop normal work.
2. Back up the current database.
3. Make sure you have the correct SQLite backup file.
4. Tell operators not to issue or return assets during restore.

Restore steps:

1. Select `Admin`.
2. Select `Restore Database`.
3. Choose the SQLite backup file.
4. Select `Validate Backup`.
5. Review the validation summary.
6. Confirm the backup is the correct file.
7. Enter your admin password.
8. Select `Replace Live Database`.

Expected result:

- AssetTrack replaces the live database with the backup.
- AssetTrack keeps a rollback copy.
- Recovery mode turns on.

Restore does not create custody events. Restore does not rebuild work that happened after the selected backup.

## Recovery Mode

**Admin only**

Recovery mode tells the site to review the restored database before normal email delivery resumes.

After restore:

1. Select `Admin`.
2. Select `Admin Tools`.
3. Confirm `Recovery Mode Active` appears.
4. Review the restore details.
5. Check Dashboard, Reports, and Receipts.
6. Confirm the restored data is correct.
7. Select `Acknowledge Recovery and Resume`.

Expected result:

- Recovery mode clears.
- Receipt send, retry, and resend actions can resume.

Do not acknowledge recovery until the review is complete.

## Log Out

1. Select your account or logout control.
2. Select `Logout`.
3. Confirm the login page appears.

After logout, protected pages should not open until you log in again.

## When Something Looks Wrong

1. Stop before committing.
2. Read the warning or blocked message.
3. Search for the asset.
4. Check the holder.
5. Check the case and slot.
6. Ask an admin for help if the record still looks wrong.

Do not use corrections to skip normal Issue, Return, or slot-move steps.
