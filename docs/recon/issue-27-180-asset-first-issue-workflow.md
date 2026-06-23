# Issue 27-180 Recon: Asset-First Issue Workflow

## Summary

Recommendation: move to asset-first staging in a dedicated implementation issue.

Why it matters: field operators may start with the asset in hand. Asset-first
entry can surface asset status earlier, but Issue still transfers custody to a
holder. Any change must keep holder responsibility, preview intentionality, and
append-only commit behavior intact.

This recon is documentation only. It does not change routes, templates, tests,
queue behavior, preview behavior, commit behavior, custody logic, receipt
behavior, schema, persistence, or role enforcement.

## 1. Current Holder-First Workflow Summary

Current Issue flow:

```text
/issue
-> active holder selection through /holders?return_to=/issue
-> current location selection on /issue
-> scan queue
-> /issue/preview
-> /issue/commit
-> receipt detail
```

Current behavior verified from `assettrack/intake/app.py`,
`return_queue.html`, `issue_preview.html`, and focused Issue tests:

- `GET /issue` enables `session["issue_mode"]`.
- If no active holder is selected, `/issue` flashes `Select a holder before
  issuing assets.` and redirects to `/holders?return_to=/issue`.
- Holder search sanitizes `return_to` with the safe local rule: path starts
  with `/` and does not start with `//`.
- Holder selection returns to `/issue`.
- Current location is validated after holder selection and may be constrained
  by the selected holder's organization-building mappings.
- Scan submission to `/` with `return_to=/issue` requires an active holder and
  valid current location before adding to `SCAN_QUEUE`.
- Queue entries are staged only; they do not mutate custody.
- `/issue/preview` requires Issue mode and a non-empty queue, then renders
  holder, current location, queued assets, blocked items, and commit controls.
- `/issue/commit` requires review confirmation, responsibility acknowledgment,
  active holder, valid current location, and queued assets.
- `_issue_batch()` revalidates queued assets, updates asset custody state,
  vacates slot occupancy, appends `ISSUE` events, and creates a receipt queue
  row from committed event data.

Current tests encode holder-first assumptions in:

- `tests/test_issue_holder_prerequisite.py`
- `tests/test_issue_location_wiring.py`
- `tests/test_issue_23_2_preview_commit_seam.py`
- `tests/test_issue_case_scan.py`
- `tests/test_issue_clear_queue.py`
- `tests/test_issue_slot_occupancy_consistency.py`
- `tests/test_issue_23_1_active_queue_timestamps.py`

## 2. Proposed Asset-First Workflow Summary

Proposed constrained asset-first flow:

```text
/issue
-> scan or identify asset into staged Issue queue
-> show current asset state and issuability
-> choose receiving holder
-> set current location
-> /issue/preview
-> /issue/commit
-> receipt detail
```

Required guardrail: asset-first must mean asset-first staging, not asset-first
custody transfer.

Safe target behavior:

- `/issue` renders the Issue workflow page directly.
- The page can accept scans before holder selection.
- Scanned assets remain staged, not issued.
- The queue can show asset state: current holder, current location, storage
  state, slot state, and blocking issues.
- Preview readiness remains blocked until an active holder and valid current
  location are selected.
- Commit remains impossible without holder, current location, review
  confirmation, responsibility acknowledgment, and a valid queue.
- Events and receipts continue to derive from commit-time validation only.

## 3. Benefits Of Asset-First

- Matches field behavior when the operator starts with a barcode or machine.
- Surfaces unavailable assets earlier: unknown tag, retired/disposed, not in
  storage, not currently slotted, or already in custody.
- Lets the operator answer "what is this and can it move?" before searching for
  the receiving holder.
- Reduces wasted holder lookup when the asset is not issuable.
- Can make one-off issue work faster without weakening the final custody gate.
- Aligns with Milestone 27 direction to favor asset-first review while
  preserving the workflow seam.

## 4. Risks Of Asset-First

- Operators may treat staged assets as already issued if copy and layout are
  not explicit.
- Queue state without a holder can obscure who is accountable for the handoff.
- Preview could feel asset-centered and make holder responsibility look like a
  late form field.
- Current location validation is currently holder-aware; moving scans earlier
  must not weaken organization-building constraints.
- The shared in-memory `SCAN_QUEUE` could become harder to reason about when
  scans happen before holder selection.
- Existing tests intentionally enforce holder-first entry and scan behavior.
- Generic `/preview` still exists as a direct review surface; asset-first Issue
  must not make generic preview the Issue entry route.
- Route redirects could accidentally send `/issue` or holder selection directly
  to preview, violating the protected seam.

## 5. Invariants That Must Be Protected

- Events remain append-only.
- Audit history is never modified or deleted.
- System state derives from event history.
- Asset custody state reconciles with the event log.
- Issue preview never changes custody.
- Issue queue state remains deterministic and staged.
- Issue commit appends `ISSUE` events only after final validation.
- No event or receipt is created without an active holder.
- No asset is committed without responsibility acknowledgment.
- Offline-first operation remains intact.
- SQLite persistence and schema remain unchanged unless separately approved.
- Role enforcement remains local and non-bypassable.
- Required seam remains explicit:

```text
entry page
-> prerequisite selection
-> scan queue
-> preview
-> commit
```

For asset-first, the safe interpretation is:

- entry page: `/issue`
- prerequisite selection: select workflow intent and stage asset identity
- scan queue: staged asset queue with blocked/ready status
- preview: allowed only after holder and location prerequisites are complete
- commit: append-only custody transfer

## 6. Affected Routes, Templates, And Tests

Routes and helpers:

- `GET /issue`: currently redirects to holder search when no holder is selected.
- `POST /` with `return_to=/issue`: currently blocks scans when holder or
  current location is missing.
- `_queue_redirect_target()`: currently preserves `/issue#queue-actions`.
- `_return_to_path()`: normalizes fragment-bearing return targets for workflow
  checks.
- `_safe_local_return_to()`: protects `return_to` by accepting only local paths
  beginning with `/` and not `//`.
- `_selected_holder_from_session(require_active=True)`: clears inactive holder
  selection.
- `_holder_selection_requires_active_filter()`: makes `/issue` holder selection
  active-only.
- `_validate_issue_location_form()`: currently requires selected holder before
  location can validate.
- `_build_issue_preview_state()`: already supports blocked state when holder is
  missing, but current entry/scan gates usually prevent reaching that path.
- `GET /issue/preview`: blocks empty queue and redirects to `/issue`.
- `POST /issue/commit`: rejects missing Issue mode, missing confirmations,
  missing holder, invalid location, empty queue, and invalid assets.
- `_issue_batch()`: final custody mutation and append-only event creation.

Templates:

- `assettrack/intake/templates/return_queue.html`: shared Issue/Return queue
  surface; Issue copy currently says to select holder, set current location,
  then scan.
- `assettrack/intake/templates/issue_preview.html`: Issue review, holder
  responsibility, current location, asset readiness, and commit confirmation.
- `assettrack/intake/templates/holders_search.html`: holder selection preserves
  `return_to=/issue` and uses Issue-specific action labels.
- `assettrack/intake/templates/preview.html`: generic preview remains a
  downstream/direct review surface and must not become Issue entry.
- `assettrack/intake/templates/_workflow_context_banner.html`: selected holder
  and queued-count context.

Tests:

- `tests/test_issue_holder_prerequisite.py`: must be rewritten or split because
  it asserts `/issue` redirects before queue access.
- `tests/test_issue_location_wiring.py`: must add scan-before-location coverage
  while preserving commit-time location validation.
- `tests/test_issue_23_2_preview_commit_seam.py`: must preserve preview and
  commit seam checks.
- `tests/test_issue_case_scan.py`: must define case scan behavior before holder
  selection.
- `tests/test_issue_clear_queue.py`: must preserve holder state, queue clearing,
  and rescan behavior.
- `tests/test_issue_slot_occupancy_consistency.py`: must preserve slot
  occupancy validation and commit effects.
- `tests/test_basic_auth_guard.py`: role/session guard coverage should remain
  unchanged.
- `tests/test_return_batch.py`: nearby regression coverage because
  `return_queue.html` is shared with Return.

Docs:

- `docs/operator/workflow-model.md`
- `docs/recon/issue-27-9-issue-workflow-asset-first-model.md`
- `docs/recon/issue-27-160-issue-preview-batch-preview.md`
- this recon

## 7. Required Implementation Sequence If Approved

Use separate implementation issues. Do not combine these steps.

1. Route and queue staging change:
   - Let `/issue` render without selected holder.
   - Keep `issue_mode` enabled.
   - Allow scan submission with `return_to=/issue` before holder/location.
   - Preserve inventory validation and queue determinism.
   - Do not allow preview readiness or commit without holder/location.

2. Asset-state queue presentation:
   - Show staged asset status on `/issue`.
   - Mark unavailable assets visibly.
   - Say staged assets are not issued.
   - Keep one dominant next action.

3. Holder and location prerequisite placement:
   - Add holder selection and current-location controls after or beside the
     staged queue.
   - Preserve active-only holder selection.
   - Preserve safe `return_to=/issue`.
   - Keep location validation holder-aware.

4. Preview gate hardening:
   - Ensure `/issue/preview` redirects to `/issue` when queue is empty.
   - Ensure missing holder/current location renders blocked state or redirects
     to `/issue`, but never commits.
   - Do not redirect `/issue` directly to preview.

5. Commit revalidation:
   - Preserve all existing commit checks.
   - Assert no event, receipt, slot vacancy, or asset custody update occurs on
     blocked commits.

6. Tests:
   - Replace holder-first entry assertions with asset-first staging assertions.
   - Add scan-before-holder tests.
   - Add holder-after-staging tests.
   - Add missing-holder preview/commit blocking tests.
   - Keep existing event, receipt, slot, queue-clear, and role tests.

7. Documentation and operator smoke:
   - Update workflow model docs after behavior is implemented.
   - Run Docker rebuild and incognito smoke tests through the full Issue seam.

## 8. Required Manual Smoke Scenarios

Use Docker rebuild and incognito browser for any implementation follow-up.

1. Existing holder-first Issue flow:
   - Select holder, set current location, scan valid storage asset, preview,
     commit.
   - PASS if receipt opens, event is appended, custody moves to selected holder,
     and queue clears.

2. Proposed asset-first flow with valid asset then holder:
   - Open `/issue`, scan valid storage asset, verify staged state, select holder,
     set current location, preview, commit.
   - PASS if staged asset is not committed before preview/commit and final event
     uses the selected holder.

3. Proposed asset-first flow with unavailable asset:
   - Scan asset that is unknown, not in `STORAGE`, retired/disposed, or not
     slotted.
   - PASS if queue shows blocked state and commit creates no event or receipt.

4. Proposed asset-first flow with missing holder:
   - Scan valid asset, do not select holder, attempt preview/commit path.
   - PASS if preview readiness/commit is blocked and no custody mutation occurs.

5. Preview reached only after queue is populated:
   - Open `/issue/preview` with empty queue.
   - PASS if it returns to `/issue` and does not become an entry route.

6. Commit appends custody events and clears queue:
   - Complete valid asset-first Issue flow.
   - PASS if one `ISSUE` event per asset is appended, receipt is created from
     event data, slot occupancy is vacated, and queue clears.

7. Back/cancel behavior preserves workflow intent:
   - From `/issue`, go to holder search with `return_to=/issue`, select/cancel,
     clear queue, and return.
   - PASS if return targets remain local, `/issue` is preserved, and no path
     starts with `//`.

8. Role enforcement for operator/admin boundaries:
   - Run Issue flow as operator and admin where currently allowed.
   - Attempt protected admin-only surfaces as operator.
   - PASS if Issue remains available to logged-in operators/admins and
     admin-only routes stay protected.

## 9. Recommendation

Move to asset-first staging, not asset-first commit.

Rationale:

- Asset-first better matches field discovery when the operator starts with a
  machine, not a person.
- It can improve safety by showing asset availability before holder selection.
- The current holder-first model is internally safe, but it hides asset
  eligibility until after holder and location prerequisites.
- The change is not a copy tweak. It affects route flow, scan gates, holder
  prerequisite tests, current-location timing, and operator training.

Smallest safe next step:

- Open a Class 2 implementation issue for asset-first staging only.
- Keep schema, events, receipts, persistence, auth, and Docker/runtime behavior
  out of scope.
- Keep holder and current location mandatory before preview-ready state and
  commit.

Do not implement a broad workflow rewrite. Do not make generic `/preview` the
Issue entry route.
