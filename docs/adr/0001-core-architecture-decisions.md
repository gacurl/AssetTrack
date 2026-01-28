# ADR 0001: Core Architecture Decisions

## Status
Accepted

## Why this exists
AssetTrack is meant to be used in places where the network may be slow, unreliable, or completely unavailable. The goal is to track equipment in a way that is clear, trustworthy, and reviewable without needing servers, logins, or constant connectivity.

This document records the key decisions that guide how the system is built so future changes don’t accidentally break those goals.

## Decisions

### Offline-first by design
AssetTrack works fully offline. You should be able to run it, enter data, correct mistakes, and generate reports without an internet connection.

If the system can’t work offline, it’s not meeting its primary purpose.

### Assets always have a clear state
Every asset is always in a known state (for example: issued, returned, lost, or disposed). Assets do not jump between states randomly.

State changes are checked to make sure they make sense, and invalid transitions are blocked.

### Every meaningful change is recorded
When something important happens to an asset, that action is written to an audit log. These audit records are never edited or deleted.

This creates a clear history of what happened, when it happened, and in what order.

### Data lives locally first
All data is stored locally using SQLite. The system does not depend on cloud services or remote databases to function.

Future integrations can be added later, but they are not required for normal operation.

### Batch imports are deliberate and safe
When importing many assets at once, the system validates the data first, shows a preview, and only commits the changes if everything checks out.

This avoids half-complete imports and confusing states.

## What this means
- The system prioritizes trust and traceability over speed or convenience
- Operators can review and explain decisions after the fact
- Mistakes are visible and correctable, not hidden
- Adding online or centralized features later will require intentional design
