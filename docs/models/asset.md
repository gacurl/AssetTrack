# Asset Model (Plain Language)

This document defines what an **Asset** is in AssetTrack, in plain language (no code).  
It is the source of truth for the future SQLite schema, UI fields, batch ingest, and reporting.

## Goals this model must support

- Offline-first operation
- Untethered scanning (scanner stores scans; later upload/ingest)
- Batch issue/return (ex: issue an entire case or multiple cases)
- Accountability: the first question we must answer is **“who signed for it?”**
- Simple operator workflow (date-level accuracy is acceptable)
- Clear separation between:
  - **Who is responsible** (custody)
  - **Is it missing / at risk** (accountability)
  - **Can it be used** (condition / maintenance)

---

## Core identity

### Primary identifier (required)

**asset_tag** (string)
- Required
- Globally unique
- 1D barcode value scanned in the field
- This is the *canonical identity* for lookup and operations

Uniqueness rule:
- `asset_tag` must be unique across all assets in the local database.

Normalization rule:
- Trim whitespace
- Preserve leading zeros (do not cast to int)
- Store exactly what’s printed/scanned after trimming

### Secondary identifiers (optional / best effort)

**serial_number** (string)
- Present in practice, but treated as “best effort”
- Not enforced unique
- Used for reconciliation and sanity checks

Other optional identifiers (future-friendly, not required now):
- `manufacturer` (string)
- `model` (string)
- `model_code` (string)

---

## Required descriptive fields

**equipment_type** (enum)
- Required
- For now, we can keep this narrow (ex: `laptop`)
- Expand later if needed (tablet, printer, etc.)

---

## Location (asset-first)

Location is tracked at the **asset level** because cases are emptied during deployment and refilled at teardown.

**location_site** (string) — optional  
Examples: country, city, exercise site name

**building_room** (string) — optional  
(From your spreadsheet: `building_room`)

**case_number** (string) — optional, logistics-only  
- Represents the transport case identifier
- Helpful at issue/return time
- Not authoritative for “where the asset is during the exercise”

**slot_number** (string/int) — optional, logistics-only  
- Used when the asset is physically placed in a case slot
- Valid values depend on case type (18-slot or 30-slot cases)

Rule of thumb:
- If it helps you find it later, capture it.
- If it creates friction during deployment, it stays optional.

---

## Custody (who is responsible)

Custody is intentionally simple and flexible.

### Custody state (required)

**custody_state** (enum, required)
- `in_storage` — in our control, not issued
- `issued_to` — issued to a responsible person or org
- `returned` — returned from the field (may be same as in_storage depending on workflow)
- `retired` — removed from active use

### Custody target (only required when issued)

**issued_to_name** (string)
- Required when `custody_state = issued_to`
- The accountable entity (leader or individual)
- This answers “who signed for it?”

**issued_to_role** (enum, optional; informational only)
- `leader`
- `individual`
- `org`

Note:
- Role is not authoritative; it’s just for easier reporting and filtering.

### Issue/return basics

- Batch issue to a leader = set many assets to `issued_to_name = <leader>`
- Single issue to a person = same fields, same workflow
- FCFS distribution under a leader is fine: assets can remain issued to the leader without naming individual users

---

## Accountability status (is there a problem / loss risk)

This is separate from custody and separate from condition.

**accountability_status** (enum, required)
- `normal` (default)
- `temporarily_unlocated` (we can’t find it right now; still in someone’s custody)
- `under_review` (active investigation / discrepancy being worked)
- `unaccounted_for` (confirmed missing / not recovered)
- `resolved` (issue was resolved; asset is back to normal)

Rules:
- Changing `accountability_status` must be auditable (who/when/why).
- An asset can be `temporarily_unlocated` while still `issued_to` the same person.
- Accountability status does not automatically change custody.

---

## Condition (maintenance / usability)

Maintenance is not “missing.” It lives here.

**condition** (enum, required)
- `operational` (default)
- `degraded` (usable but with issues)
- `under_maintenance` (pulled for repair / troubleshooting)
- `out_of_service` (broken, not expected to return to service during this period)

Rules:
- Changing `condition` must be auditable (who/when/why).
- Condition does not automatically change custody.
  - Example: it can remain issued_to a leader while being brought to maintenance, depending on process.
  - Or it can be returned to storage as part of maintenance intake.

---

## Audit-relevant fields (must be traceable)

We will implement audit as an append-only event log later (Milestone 2).  
For the model, this means we must be able to trace:

- Who issued it (signer / operator)
- Who it was issued to (responsible party)
- When it was issued (date is sufficient)
- When it was returned (date is sufficient)
- Any change to:
  - `custody_state`
  - `issued_to_name`
  - `accountability_status`
  - `condition`
  - location fields (if used operationally)

Minimum operator-entered audit notes:
- **reason / notes** (string, optional but strongly recommended for status changes)
- **reference** (string, optional; ex: hand receipt number, exercise name, ticket ID)

Date precision:
- Date-level is acceptable (timestamps optional later).

---

## Field summary: required vs optional

### Required
- `asset_tag`
- `equipment_type`
- `custody_state`
- `accountability_status`
- `condition`

### Conditionally required
- `issued_to_name` (required when `custody_state = issued_to`)

### Optional (recommended where practical)
- `serial_number`
- `manufacturer`, `model`, `model_code`
- `issued_to_role`
- `location_site`, `building_room`
- `case_number`, `slot_number`
- `notes` / `reference` fields tied to audit events (Milestone 2)

---

## Notes for upcoming milestones

- Milestone 2 (State & Audit Engine) will represent changes as append-only events.
- Milestone 3 (Offline Batch Ingest) will support:
  - importing scanned `asset_tag` lists
  - preview + validation
  - atomic commit for batch issue/return
- Milestone 5 (Reporting & Hand Receipts) will prioritize rollups by:
  - `issued_to_name` (who signed for it)
  - exceptions: `accountability_status != normal`
  - maintenance: `condition in (under_maintenance, out_of_service)`
