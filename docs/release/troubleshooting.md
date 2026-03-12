# AssetTrack Troubleshooting Guide

## Purpose

This guide covers common issues operators and administrators may see during startup and normal use.

## Port already in use

Symptom:

- `docker compose up -d --build` fails to start correctly
- Port `8000` is already in use

What to do:

1. Close any other local process already using port `8000`.
2. Stop any old AssetTrack container that may still be running.
3. Run `docker compose down`.
4. Run `docker compose up -d --build` again.

## Docker not running

Symptom:

- Docker commands fail immediately
- Compose cannot connect to the Docker daemon

What to do:

1. Start Docker Desktop or the local Docker service.
2. Wait until Docker reports that it is ready.
3. Re-run `docker compose up -d --build`.

## Login failure

Symptom:

- The login page loads, but the credentials do not work

What to check:

1. Confirm the username and password were typed correctly.
2. Confirm the user account is still active on the `Users` page.
3. If this is a fresh system, confirm an admin was created at `/bootstrap/admin`.
4. If needed, have an admin reset the password from `Users`.

## Scanner input issues

Symptom:

- A scan does not appear
- One trigger creates multiple entries
- The scanned text is wrong or incomplete

What to do:

1. Click once in the scan box before scanning.
2. Test the scanner in a plain text application like TextEdit, Notepad, or Notes.
3. Confirm the scanner behaves like a keyboard and sends Enter at the end of each scan.
4. If the problem appears in plain text too, fix the scanner or cable first.

For more background, see:

- [scanner_expectations.md](/Users/gacurl/IdeaProjects/AssetTrack/docs/scanner_expectations.md)

## Database persistence check

Symptom:

- You are not sure whether the database survived a restart

What to check:

1. Start the app with `docker compose up -d --build`.
2. Log in and create a simple record such as a test holder.
3. Stop the app with `docker compose down`.
4. Start it again with `docker compose up -d --build`.
5. Confirm the record still exists.

Why this works:

- AssetTrack stores SQLite data at `/app/data/assettrack.db`
- The Docker Compose setup keeps that data in the mounted `./data` directory
- Normal stop/start cycles do not erase the database

## Queue or preview confusion

Symptom:

- The queue does not commit
- The preview page shows a blocked batch

What to check:

1. Read the validation summary first.
2. Confirm the queue contains the right asset tags.
3. Confirm the selected holder is correct for issue workflows.
4. Confirm the asset is in the correct current state for the requested action.
5. Confirm the final confirmation checkbox is checked before commit.

## When to escalate

Escalate for deeper review if:

- the app will not start after Docker is confirmed healthy
- the login page is unreachable on `http://localhost:8000`
- dashboard counts do not reconcile after a completed workflow
- an issue or return appears to succeed but custody state is wrong
- data disappears after a normal stop/start cycle
