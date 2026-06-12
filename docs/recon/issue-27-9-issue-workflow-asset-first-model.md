# Issue 27-9 Recon: Issue Workflow Asset-First Model

## Current Issue Workflow Summary

Recommendation: keep holder-first for deployment.

Why it matters: Issue is the custody-transfer workflow. The committed truth is
not just that a machine moved; it is that a specific holder accepted custody for
the queued machines. Starting with the holder keeps the custody actor visible
before scan, preview, and commit.

Reviewed:

- `assettrack/intake/app.py`
- `assettrack/intake/templates/return_queue.html`
- `assettrack/intake/templates/issue_preview.html`
- `assettrack/intake/templates/preview.html`
- `docs/operator/workflow-model.md`
- `tests/test_issue_holder_prerequisite.py`
- `tests/test_issue_location_wiring.py`
- `tests/test_issue_23_2_preview_commit_seam.py`
- `tests/test_issue_case_scan.py`
- `tests/test_issue_clear_queue.py`
- `tests/test_basic_auth_guard.py`

Current Issue seam:

```text
entry -> prerequisite selection -> scan queue -> preview -> commit
```

Current Issue route flow:

1. `GET /issue`
2. active holder selection through `/holders?return_to=/issue`
3. current location selection on `/issue`
4. scan individual asset tags or case tags into the shared scan queue
5. `GET /issue/preview`
6. `POST /issue/commit`
7. receipt detail redirect after commit

The route is not asset-first today. `/issue` does not render the queue until an
active holder is selected.

## Holder-First Behavior Summary

Holder selection is required before Issue queue access.

Verified behavior:

- `GET /issue` enables `session["issue_mode"] = True`.
- If no active `session["holder_id"]` exists, `/issue` flashes `Select a holder
  before issuing assets.` and redirects to `/holders?return_to=/issue`.
- Holder search/select returns to `/issue`.
- The Issue page shows selected holder context through the workflow banner.
- Issue location is validated against the selected holder and organization
  building mappings when present.
- Scan submission to `/` with `return_to=/issue` checks selected holder and
  current location before adding to the queue.
- Issue Preview repeats the selected holder and states: `Holder is the custody
  actor. Location and case/slot are context only.`
- Issue commit requires both review confirmation and responsibility
  acknowledgment.

Holder selection is required at these points:

| Point | Behavior |
| --- | --- |
| `/issue` entry | Redirects to holder search when no active holder is selected. |
| scan submission with `return_to=/issue` | Rejects scan and sends operator to holder search when no holder is selected. |
| `_build_issue_preview_state()` | Adds blocking issue when selected holder is missing. |
| `/issue/commit` | Rejects commit when holder is missing. |
| `_issue_batch()` | Receives required `holder_id` and writes it into asset state, events, and receipt snapshot. |

## Asset Entry and Queue Behavior Summary

Assets are added after holder and current location prerequisites.

Supported Issue queue entry:

- scan or type a single asset tag
- scan or type a case tag that expands to eligible assets in that case
- remove one queued item by queue index
- clear the queue
- launch Issue Preview from the queue page

Queue behavior:

- The queue is in memory through `SCAN_QUEUE`.
- Duplicate asset tags are rejected.
- Issue scans require the asset to exist in inventory.
- Case scans expand to storage assets currently slotted in the matching case.
- Queue entries are staged only; they do not change custody.
- Preview validates queued assets before commit.

Issue Preview validation checks:

- queue is not empty
- holder is selected
- current location is valid
- each asset exists
- each asset is not terminal/retired
- each asset is currently `STORAGE`
- each asset is currently slotted

Commit behavior:

- `POST /issue/commit` requires Issue mode.
- Commit requires `confirm_reviewed`.
- Commit requires `confirm_responsibility_ack`.
- Commit revalidates holder, current location, and queue.
- `_issue_batch()` updates each asset to `IN_CUSTODY`.
- `_issue_batch()` sets `current_holder_id` to the selected holder.
- `_issue_batch()` vacates slot occupancy.
- `_issue_batch()` appends one `ISSUE` event per asset.
- The `ISSUE` event payload records from/to location type, from/to
  building-room context, home slot, and responsibility acknowledgment.
- Receipt queue row is created from stored event history.
- Receipt delivery remains convenience metadata and is not custody truth.

## Operator Friction Points

- If the operator physically starts by scanning machines, the holder-first gate
  interrupts that instinct.
- A new operator may not know the holder must be selected before the scanner
  becomes useful.
- Current location is a second prerequisite before scanning, which adds another
  pause before queue work.
- Case-scan issuing is fast once prerequisites are set, but the first-use path
  is not purely scan-first.
- Holder-first works well for batch handoff to a known person or organization,
  but less naturally for ad hoc "I have this machine in my hand" lookup moments.

## Holder-First Benefits

- Keeps the custody actor visible before any queued transfer.
- Matches the model: holder = custody actor, location = transaction context,
  case/slot = storage logistics.
- Reduces risk that operators confuse location, case, slot, or scanned machine
  with the accountable party.
- Makes responsibility acknowledgment concrete at preview/commit.
- Produces issue events with a single selected holder for the batch.
- Produces receipt snapshots with a clear holder and recipient context.
- Keeps the workflow aligned with `entry -> prerequisite selection -> scan queue
  -> preview -> commit`.
- Avoids queue entries that look ready but cannot legally commit because no
  custody actor exists.

## Asset-First Benefits

Asset-first could help in specific field moments:

- Operator starts with a barcode in hand and wants to scan immediately.
- Teardown or fast distribution may be machine-driven before the holder is
  confirmed.
- Scan-first flow could feel faster for one-off handoffs.
- Early asset scan could reveal blocked states sooner: unknown tag, retired,
  not in storage, not slotted, or already out.
- It may reduce the cognitive jump from "I am holding this laptop" to "first
  search/select a holder."

Asset-first is not automatically safer. It only helps if the workflow still
forces holder selection and responsibility acknowledgment before preview/commit.

## Custody Truth Risks

Asset-first risks custody truth if implemented loosely.

Risks:

- Operators may treat queued assets as issued before a holder accepts custody.
- A queue could accumulate assets without a custody actor, creating ambiguous
  handoff intent.
- Preview could become asset-centered and make holder responsibility feel like a
  late form field.
- Receipts could become harder to explain if the holder is not selected before
  review.
- Event payloads depend on `holder_id` and responsibility acknowledgment at
  commit. Any asset-first change must not weaken that requirement.
- Location or case context could be mistaken for custody actor if holder
  selection is delayed too far.
- Shared queue state could become confusing if operators switch from asset-first
  staging into holder selection and back.

Hard safeguards required for any future asset-first experiment:

- No commit without active holder.
- No preview-ready state without active holder.
- No event without `holder_id`.
- No receipt snapshot without event-derived holder truth.
- No schema change unless separately approved.
- Clear wording that scanned assets are staged only, not issued.
- Holder remains the custody actor.

## Recommendation

Keep holder-first for deployment.

Why:

- The current model is internally consistent and covered by focused tests.
- The strongest deployment question is proof: who had the machine, what moved,
  and what receipt/event proves it. Holder-first protects the "who had it" part
  before assets can be committed.
- Field speed matters, but Issue is a custody-transfer action. Scanning first is
  convenient only if it does not obscure who accepted responsibility.
- About 50 days from deployment, changing workflow order would create training,
  testing, and audit-risk churn.

Do not move Issue to asset-first before deployment without operator validation
and a separate implementation issue with strict custody safeguards.

## Smallest Safe Follow-Up

Create an operator-validation follow-up, not an implementation issue.

Suggested follow-up:

```text
Issue 27-9 follow-up: Validate holder-first Issue workflow with field operators
```

Scope:

- Run two timed paper or staging walkthroughs:
  1. batch issue to a known holder
  2. ad hoc single-machine issue where the operator starts with the machine
- Observe whether operators naturally ask "who is receiving this?" before
  scanning or start by scanning the asset.
- Record friction around holder selection, current location, queue, preview, and
  responsibility acknowledgment.
- Do not change routes, schema, queue, preview, commit, events, receipts, or
  custody semantics.

If operator validation proves asset-first is needed, open a later implementation
issue for "asset-first staging only" with these boundaries:

- assets may be staged before holder selection
- preview-ready and commit remain blocked until holder and current location are
  selected
- events and receipts remain holder-derived custody proof
- tests must cover scan-before-holder, holder selection after staging, preview
  blocking, commit blocking, event holder_id, receipt holder_id, and queue clear
  behavior

## Explicit Non-Changes Confirmation

This recon did not change:

- Issue routes
- Return routes
- queue behavior
- preview behavior
- commit behavior
- holder semantics
- custody actor truth
- custody logic
- event behavior
- receipt behavior
- schema or migrations
- permissions
- dependencies
- tests
- workflow seam
