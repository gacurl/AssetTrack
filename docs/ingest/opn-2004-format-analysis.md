# OPN-2004 Offline Ingest Format — Analysis

## Why this exists

This document defines the file format AssetTrack will accept for **offline batch ingest**.

The goal is simple:
- capture assets in the field (scanner or manual entry)
- review the data before it touches the database
- commit it safely, all at once

This is intentionally boring and explicit.  
No parsing code, validation logic, or database writes should exist until this format is agreed on.

---

## Design goals (plain English)

- Works offline
- Easy to open, read, and fix by a human
- One row means one thing happened to one asset
- Nothing is deleted
- History is preserved
- Data is reviewed before it’s committed
- Commits are all-or-nothing

If something breaks, another person should be able to figure it out without calling the original author.

---

## File format

**CSV (comma-separated values)**

Why CSV:
- Scanners can produce it
- Excel can open it
- Humans can fix it
- SQLite can ingest it cleanly
- No extra tooling required in the field

If the scanner later produces something else, we can revisit this. For now, CSV is the right tradeoff.

---

## Required columns

These columns **must** be present in every file and every row.

| Column | What it means |
|------|----------------|
| asset_tag | Stable identifier for the asset |
| timestamp | When the event occurred (ISO-8601 format, UTC preferred) |
| event_type | What happened (scan, issue, return, update, retire) |
| issued_to_name | Who is accountable for the asset |
| operator_id | Username of the person performing the scan/import |
| case_number | Transport/storage case identifier |
| slot_number | Slot inside the case where the asset belongs |

If any required field is missing or empty, the row is rejected during preview.

---

## Optional columns

These are included when known. They are not required for every row.

| Column | What it means |
|------|----------------|
| building_room | Physical room or space |
| equipment_type | Type/category (required only when creating a new asset) |
| serial_number | Manufacturer serial number |
| manufacturer | Manufacturer name |
| model | Model name |
| model_code | Internal/shorthand model code |
| notes | Free-text notes for human context |

Optional does **not** mean ignored — it just means the system won’t block the batch if they’re missing.

---

## What a row represents

Each row represents **one event for one asset**.

The system does not:
- guess intent
- infer meaning across rows
- auto-correct data

If something needs to change, it should be explicit in the file.

---

## Checking out laptops and moving assets between cases/slots

`case_number` and `slot_number` are required because every asset must always have a physical “home.”

Checking out a laptop, returning it, or moving it between cases or slots is handled as an **event**, not as a silent edit.

Example:
- Moving a laptop from one slot to another is recorded with `event_type=update`
- The row includes the *new* `case_number` and `slot_number`

If an asset is temporarily not in a case (issued, in use, repair, etc.), the batch must still set a clear value
(e.g., `case_number=OUT`, `slot_number=OUT`, or `case_number=ISSUED`, `slot_number=N/A`).

The goal is to avoid “unknown” placement while keeping the process simple and explicit.

---

## Event semantics

Event types (v1 set):
- `scan`
- `issue`
- `return`
- `update`
- `retire`

Notes:
- `scan` is observation-only unless paired with explicit field changes (no state change by default).
- `issue` and `return` are custody/accountability events.
- `update` is used for changes like slot moves, location corrections, metadata corrections.
- `retire` marks an asset as retired (no delete).

---

## Duplicate and ordering rules

- The same `asset_tag` may appear multiple times in a single file
- Rows are processed in file order
- Conflicts are surfaced during preview, not during commit
- Nothing is silently overwritten

---

## Preview-time errors (no data written)

Rows are flagged and blocked from commit if:
- `asset_tag` is missing or malformed
- `timestamp` is invalid
- `event_type` is unknown
- `issued_to_name` is empty
- `case_number` or `slot_number` is empty
- the referenced asset does not exist (unless the event creates it)

The goal is to catch problems **before** the database changes.

---

## Create behavior (new assets)

Creating a new asset is allowed during batch ingest.

Rule:
- If `asset_tag` does not exist yet, the row may create it **only** if enough identifying info is present.

Minimum required for create:
- all required columns
- plus `equipment_type`

Optional but recommended on create:
- `serial_number`, `manufacturer`, `model`, `model_code`, `building_room`

If create requirements are not met, the row is rejected during preview.

---

## Mapping to AssetTrack database

This format is intended to map cleanly to the existing SQLite tables:

- `assets` (current truth / latest state)
- `asset_events` (append-only history)

Key expectations:
- `issued_to_name` is the field value we rely on to find the accountable person later.
- `operator_id` is the person performing the scan/import (stored in the event record).
- `case_number` and `slot_number` represent the current “home” location for the asset.

---

## Commit behavior (out of scope)

Atomic commit rules are intentionally **out of scope** here.

They are defined in:
- Issue 3-4 — Atomic batch commit

This document only defines the ingest contract.
