# Docker data persistence — why it matters for AssetTrack

## TL;DR

When AssetTrack runs inside Docker, it has its own filesystem.
If nothing is configured, the database exists only inside the container and disappears when the container stops.

To make data portable and durable, the host data directory must be mounted into the container at /app/data.

This behavior is required, not optional.

## The problem this solves

During troubleshooting, the following behavior was observed:

A scan was committed successfully.
The UI reported that an item was added.
Querying the database on the host showed no new rows.

Nothing was broken.

The application was writing to a database file inside the container located at `/app/data/assettrack.db`,
while the host was querying a different database file with the same name located at `/app/data/assettrack.db`.

The paths looked similar, but they pointed to different filesystems.
Same filename. Different filesystems.

## How Docker filesystems work

A Docker container has its own isolated filesystem.

It cannot see files on the host unless they are explicitly shared.
When a container is removed, any files inside it are lost.

A volume mount is how we share a folder between the laptop and the container.

## AssetTrack’s rule

All persistent data must live outside the container.

For AssetTrack, this means:

Code is baked into the Docker image.
The database is mounted from the host.

This keeps the system offline-friendly, inspectable, recoverable, and portable.

## Required way to run AssetTrack in Docker

AssetTrack must always be run with the host data directory mounted into the container’s /app/data directory.

This ensures the application and the host are reading and writing the same database file.

## How to verify it’s working

After starting the container with the volume mount:

Scan and commit an asset through the UI.
Query the host database file.

If the newly committed asset appears, persistence is working correctly.

## Why this makes AssetTrack portable

With this setup:

Containers can be destroyed and recreated safely.
Data survives restarts.
The same image works on any machine.
The data folder can be backed up or moved.

The container becomes stateless.
The data becomes portable.

This is exactly what we want for a field-ready, offline-first system.

## One sentence to remember

If you don’t mount the host data directory into Docker, you are writing to a disposable database.