# AssetTrack Operator Manual

Version: Milestone 13 Baseline  
Audience: Field Operators and Supervisors  

---

## 1. Purpose of This System

AssetTrack is an offline-first asset accountability system designed to:

- Track physical assets in storage
- Track assets issued to individuals (custody)
- Enforce disciplined, atomic state transitions
- Maintain an append-only audit trail

The system is intentionally strict.  
If an action is blocked, it is blocked for a reason.

---

## 2. Mental Model: Storage vs Custody

There are only two primary active states:

### STORAGE
- Asset is physically in storage.
- Asset occupies a specific slot.
- Asset has no active holder.

### IN_CUSTODY
- Asset is issued to a holder.
- Asset is not in a slot.
- Asset has an active holder.

Terminal states (Retired / Disposed) remove assets from operational circulation.

The system enforces this model consistently.

---

## 3. Roles and Permissions

### Operator
- Logs in via splash screen.
- Can stage assets.
- Can preview workflows.
- Can initiate issue and return flows.

### Supervisor
- Required for commit operations.
- Required for admin actions.
- Authenticated via HTTP Basic credentials (configured separately from login session).
- Can create, retire, replace assets.
- Can assign, move, or force-vacate slots.
- Can correct events (append-only corrections).

Supervisor actions are explicitly protected.

---

## 4. Logging In

1. Navigate to `/`
2. Enter login credentials.
3. Successful login redirects to `/dashboard`.

If unauthenticated, all protected routes redirect to `/`.

### Locking the System
- `/lock` clears session authentication.
- `/logout` clears session and redirects to `/`.

---

## 5. Dashboard Overview

The dashboard provides:

- Summary view of assets
- Holder drill-down
- Case drill-down
- Slot visibility

Dashboard routes:
- `/dashboard`
- `/dashboard/holders`
- `/dashboard/cases`

Dashboard is read-only.

---

## 6. Intake Workflow (Scan → Preview → Commit)

### Step 1 — Staging (Scan Queue)

- Scanned assets are staged in memory.
- Staging queue is NOT database-backed.
- Restarting the application clears the queue.

This queue must be committed to persist.

---

### Step 2 — Preview

Navigate to `/preview`.

The preview page shows:
- Staged rows
- Validation results
- Blocking errors (if any)

Commit is not allowed until:
- At least one row is staged
- Validation passes
- Confirmation checkbox is checked
- Required contextual inputs are present

---

### Step 3 — Commit (Normal Ingest Mode)

On successful commit:
- Batch is written atomically.
- Events are recorded.
- Queue is cleared.
- Holder selection cleared.
- Redirect to `/`.

On failure:
- Errors are displayed.
- No partial writes occur.

---

## 7. Issuing Assets (Issue)

Issue moves assets from STORAGE to IN_CUSTODY.

### Preconditions

- Operator logged in.
- Supervisor authentication provided.
- Holder selected.
- Queue contains valid asset tags.
- Asset is in STORAGE.
- Asset is slotted.
- Asset is not retired/disposed.
- Confirmation checkbox checked.

### Blocking Conditions

- Unknown asset tag.
- Asset not in STORAGE.
- Asset not slotted.
- Retired/disposed asset.
- No holder selected.
- Empty queue.

### On Successful Issue

- `location_type` → IN_CUSTODY
- `current_holder_id` set
- Slot vacated
- ISSUE event logged
- Queue cleared
- Holder cleared
- Redirect to `/`

---

## 8. Returning Assets (Return)

Return moves assets from IN_CUSTODY to STORAGE.

### Preconditions

- Operator logged in.
- Supervisor authentication provided.
- Asset in IN_CUSTODY.
- Asset not retired/disposed.
- Asset has a home slot.
- Home slot is empty.
- Confirmation checkbox checked.

### Blocking Conditions

- Asset not in custody.
- Home slot occupied.
- Missing home slot mapping.
- Unknown asset tag.
- Empty queue.

### On Successful Return

- `location_type` → STORAGE
- `current_holder_id` cleared
- Slot reoccupied
- RETURN event logged
- Queue cleared
- Redirect to `/return`

---

## 9. Blocking Conditions Explained

The system blocks actions when:

- Asset state conflicts with requested transition.
- Required contextual data is missing.
- Supervisor authentication fails.
- Validation errors exist.
- Confirmation checkbox not checked.

Blocking is intentional and protects data integrity.

---

## 10. Supervisor Actions

Supervisor-only routes include:

- Create asset
- Retire asset
- Replace asset
- Assign slot
- Move slot
- Force-vacate slot
- Correct events

These actions:
- Require HTTP Basic credentials.
- Use atomic transactions.
- Append audit events.
- Never modify history in place.

### Event Corrections

Event corrections:
- Insert a new correction row.
- Reference the superseded event.
- Do not delete or rewrite prior events.

Audit trail remains intact.

---

## 11. Data Safety & Persistence

### Queue Persistence
- Scan queue is memory-only.
- Restarting clears staged items.

### Database Persistence
- SQLite database stored at configured path.
- In Docker, persisted via mounted volume.
- Survives container restart and rebuild (with volume).

### Irreversible Actions
- Retire/Dispose transitions.
- Event corrections (append-only).
- Slot force-vacate operations.

---

## 12. Common Errors & Recovery

| Scenario | Likely Cause | Action |
|----------|--------------|--------|
| Asset cannot be issued | Not in STORAGE | Return asset first |
| Asset cannot be returned | Not in IN_CUSTODY | Verify custody state |
| Home slot occupied | Slot conflict | Supervisor intervention required |
| Commit button blocked | Confirmation not checked | Check confirmation |
| 401/503 on commit | Supervisor auth missing | Verify admin credentials |

---

## 13. Guardrails (What the System Will Not Allow)

- Partial commits.
- Silent state changes.
- Editing historical events.
- Issuing retired assets.
- Returning non-custody assets.
- Double-slot occupancy.
- Double-custody state.

If the system blocks an action, investigate state mismatch.

---

## 14. Operational Discipline Rules

1. Always review preview before commit.
2. Never ignore blocking warnings.
3. Use Supervisor actions sparingly.
4. Treat force-vacate as corrective, not routine.
5. Restarting clears queue — commit before restarting.
6. Corrections append; they do not erase.

---

End of Manual  
