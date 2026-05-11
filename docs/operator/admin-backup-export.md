# Admin Database Backup Export

Use this procedure when an admin needs a downloadable copy of the current SQLite database.

## Who can use it

- admin only
- operator accounts should expect access to be blocked

## How to reach it

1. Log in as an admin.
2. Open `Admin Tools` from the main navigation.
3. Select `Download Database Backup`.

Expected result:

- the browser downloads a `.db` file

## Downloaded file

Expected filename pattern:

`assettrack-backup-YYYYMMDD-HHMMSS.db`

Notes:

- the timestamp is generated at download time
- the file is a snapshot of the current database file
- this export is a backup download, not a restore or import action

## Operator handling

Do this:

- store the downloaded file in a controlled backup location
- keep the original timestamped filename
- record when and why the backup was taken

Verify this:

- the download completed successfully
- the file has a `.db` extension
- the file is not empty

Do not do this:

- do not treat the download as a restore operation
- do not overwrite the live database file without following the restore runbook
