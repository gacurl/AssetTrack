# Issue 27-17: Recon Validation Flow and Redundancy

## Conclusion

Issue and Return preserve the required workflow seam:

`entry page -> prerequisite selection -> scan queue -> preview -> commit`

The preview page is the primary operator validation point before custody events
are appended. Commit-time revalidation is also required. It protects against
stale queue state and concurrent storage changes between preview and commit.

The safest future simplifications are presentation changes: reduce repeated
helper text, combine repeated summaries, and demote secondary links. Do not
remove validation checks because the same fact appears on more than one page.

This recon uses `docs/operator/pre-event-validation-checklist.md` as the
guardrail.

## Current Issue Validation Flow

### Entry and prerequisites

1. `GET /issue` requires login.
2. Issue requires an active selected holder before queue work.
3. Issue separately requires a current building and room.
4. When organization-to-building mappings exist for the selected holder's
   organization, the selected building must be one of those mapped buildings.
5. Scans are blocked until the holder and current location prerequisites are
   valid.

### Queue and preview

1. The Issue queue shows staged assets, supports remove and explicit clear
   actions, and links to `GET /issue/preview`.
2. Queue rendering computes blocked conditions early for operator feedback.
3. Issue Preview requires a non-empty queue.
4. Issue Preview rechecks holder, location, and asset eligibility.
5. It shows holder, transaction location, per-asset transition facts, storage
   context, and blocked items before commit.

### Commit boundary

1. `POST /issue/commit` requires login.
2. It requires both explicit confirmations:
   - the operator reviewed the batch
   - the selected holder accepted responsibility
3. It rechecks the selected active holder, authenticated operator, current
   location, and non-empty queue.
4. `_issue_batch` validates asset eligibility again inside the atomic database
   transaction before appending Issue events and creating receipt truth.
5. The queue clears only after a successful commit.

## Current Return Validation Flow

### Entry and queue

1. `GET /return` requires login.
2. Return does not require holder or location selection. It derives the prior
   holder and assigned home slot from each asset's current state.
3. The Return queue shows staged assets, supports remove and explicit clear
   actions, and links to `GET /return/preview`.
4. Queue rendering computes blocked conditions early for operator feedback.

### Preview

1. Return Preview recomputes blocked conditions.
2. It shows each asset's current custody state and return destination.
3. It blocks commit for unknown assets, assets not in custody, retired or
   disposed assets, missing home slots, and occupied home slots.
4. The commit form is not shown while blockers remain.

### Commit boundary

1. `POST /return/commit` requires login.
2. It requires both explicit confirmations:
   - the operator reviewed the batch
   - responsibility for the return batch was acknowledged
3. It recomputes preview-state blockers before commit.
4. `_return_batch` validates asset and home-slot eligibility again inside the
   atomic database transaction.
5. Slot assignment fails closed if a home slot becomes occupied during commit.
6. The queue clears only after a successful commit.

## Receipt and Email Boundary

Issue and Return receipt snapshots are created from committed stored facts.
Receipt email, receipt resend, and holder follow-up email happen after custody
truth exists.

Keep this separate from pre-event validation:

- email delivery success is not required to append custody truth
- receipt resend does not regenerate custody truth
- holder follow-up email is operational communication only

## Findings by Classification

### Keep as-is

- **Preview remains a distinct step.**
  It is the primary operator review checkpoint before append.
- **Commit requires explicit review confirmation.**
  The operator must deliberately confirm the reviewed batch.
- **Responsibility acknowledgment remains separate from review confirmation.**
  These confirmations record different operational facts.
- **Issue requires holder and current location prerequisites before scanning
  and before commit.**
  Holder is the custody actor. Location is transaction context.
- **Return validates assigned home slots.**
  Restoring storage state must reconcile with slot occupancy.
- **Queue validation remains visible before preview.**
  Early feedback is useful even though preview and commit revalidate.
- **Commit handlers and transaction helpers revalidate.**
  These checks are safeguards against stale or changed state.
- **Queue clears only after successful commit or explicit clear action.**
  Failed validation must leave staged work available for correction.

### Safe to simplify later

- **Issue queue prerequisite presentation.**
  Current-location status, validation messages, and scan-blocking guidance can
  repeat the same next action. A future UI-only issue can consolidate the copy
  while keeping the prerequisite checks unchanged.
- **Return queue card count.**
  The scan controls, queue list, preview handoff, and blocked summary can be
  visually grouped more tightly while preserving their order.
- **Return Preview summary.**
  The readiness card, blocked-items card, per-row blocker text, and final
  conflict message repeat blocked state. A future UI-only issue can combine the
  high-level summary while keeping per-asset facts and commit blocking visible.
- **Issue Preview hierarchy.**
  Holder, location, blocked summary, per-asset facts, and commit controls should
  remain visible, but repeated supporting copy can be shortened.

### Wording or layout improvement only

- **Demote Issue Preview side links.**
  `Change holder` and `Update current location` are useful correction paths,
  but they should remain visually secondary to review and commit.
- **Review the Issue Preview back link.**
  `Back to Batch Preview` points to the generic `/preview` page. A future UI
  issue should confirm whether `Back to Issue Queue` is clearer without
  changing route behavior in this recon.
- **Keep blocked facts prominent without repeating full explanations.**
  Summary copy may be shorter if the specific blocker remains visible near the
  affected asset.

### Needs separate issue

- **Choose one canonical Issue preview path.**
  The repo has dedicated `/issue/preview` and legacy Issue-mode behavior inside
  generic `/preview`. Any cleanup must identify the canonical path, update
  tests, and preserve `queue -> preview -> commit`.
- **Decide whether empty Return Preview should redirect.**
  Issue Preview redirects an empty queue back to Issue entry, while Return
  Preview renders an empty state. Harmonizing this is a behavior decision, not
  a documentation cleanup.
- **Review clear-queue placement.**
  Issue exposes explicit clear actions on queue and preview surfaces. A future
  issue may simplify placement only after confirming the operator correction
  path remains obvious and deliberate.

### Dangerous to remove

- Login and active-user enforcement.
- Holder selection and active-holder checks for Issue.
- Current Issue building and room checks.
- Organization-to-building validation for Issue where mappings exist.
- Non-empty queue checks.
- Per-asset eligibility checks for current custody state.
- Retired or disposed asset rejection.
- Issue storage and slot checks.
- Return home-slot existence and occupancy checks.
- Preview as a separate review step.
- Both commit confirmations.
- Commit-time validation before the append boundary.
- Validation inside `_issue_batch` and `_return_batch`.
- Atomic transaction behavior.
- Append-only event inserts.
- Receipt creation from committed stored facts.
- Queue clearing only after success or explicit clear.

## Recommended Follow-On Issues

Open small issues independently. Do not combine them with validation logic
changes.

### Compress Issue prerequisite guidance without changing checks

Reduce repeated current-location and scan-blocking copy on the Issue queue page.
Keep holder selection, location entry, validation messages, and scan blocking
behavior unchanged.

### Combine Return Preview blocked-state summaries

Reduce duplicate blocked-state presentation while keeping the blocked summary,
specific per-asset reasons, and commit prevention visible.

### Recon canonical Issue preview routing

Decide whether dedicated `/issue/preview` should be the only Issue review path.
Document how to retire or redirect legacy generic `/preview` Issue-mode entry
without bypassing prerequisites, queue review, or commit confirmation.

### Review workflow correction links and clear-queue placement

Evaluate the Issue Preview back link, secondary correction links, and explicit
clear actions. Limit changes to reachability and presentation unless a separate
behavior issue is approved.

## Repo Evidence Reviewed

- `docs/operator/pre-event-validation-checklist.md`
- `docs/operator/workflow-model.md`
- `assettrack/intake/app.py`
- `assettrack/intake/templates/return_queue.html`
- `assettrack/intake/templates/issue_preview.html`
- `assettrack/intake/templates/return_preview.html`
- `assettrack/intake/templates/receipt_detail.html`
- `tests/test_issue_holder_prerequisite.py`
- `tests/test_issue_location_wiring.py`
- `tests/test_issue_case_scan.py`
- `tests/test_issue_clear_queue.py`
- `tests/test_issue_23_2_preview_commit_seam.py`
- `tests/test_return_batch.py`
- `tests/test_receipt_detail.py`

## Scope Confirmation

This recon does not change runtime behavior, routes, templates, tests, schema,
persistence, custody truth, receipt truth, audit history, or event history.
