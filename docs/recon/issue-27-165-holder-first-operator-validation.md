# Issue 27-165: Holder-First Issue Workflow Operator Validation

## Date Of Validation

2026-06-12

## Validation Method

Recon and reasoned operator smoke validation against current app behavior.

No implementation was performed. No browser smoke test was run. A full manual
smoke test would still require `docker compose up -d --build` and an incognito
browser session before deployment signoff.

Reviewed:

- `assettrack/intake/app.py`
- `assettrack/intake/templates/return_queue.html`
- `assettrack/intake/templates/issue_preview.html`
- `docs/recon/issue-27-9-issue-workflow-asset-first-model.md`
- `docs/operator/workflow-model.md`

Current protected seam:

```text
entry -> prerequisite selection -> scan queue -> preview -> commit
```

## Scenarios Tested

### 1. Known-Holder Batch Issue

Scenario: the operator already knows who is receiving the machines and scans
multiple assets into the Issue queue.

Expected operator path:

1. Log in.
2. Open Issue.
3. Select holder if not already selected.
4. Set current building and room.
5. Scan multiple asset tags or a case tag.
6. Review queue.
7. Open Issue Preview.
8. Confirm holder, location, assets, and responsibility language.

Result: PASS by current behavior.

What worked:

- `/issue` keeps the operator in Issue mode.
- Holder context is visible before scanning.
- Current Location appears before Add to Queue.
- Scan entries are staged in the queue and do not commit custody.
- Case scans can add multiple eligible storage assets.
- Preview shows holder, current location, assets, blocked items, and commit
  confirmation.

Where the operator slowed down:

- The operator must set holder and location before scan work starts.
- This is acceptable for a known-holder batch because the handoff actor is known
  upfront.

Confusing labels or buttons:

- No blocking label issue found.
- `Review Before Issue` is clear for this scenario.

### 2. Single-Machine Ad Hoc Issue

Scenario: the operator starts with one machine in hand and must issue it to a
holder.

Expected operator path:

1. Log in.
2. Open Issue.
3. If no holder is selected, select the holder.
4. Set current location.
5. Scan or enter the single asset tag.
6. Open Issue Preview.
7. Confirm responsibility and commit only if using safe data.

Result: PASS with friction.

What worked:

- The workflow prevents the operator from treating the scan as custody transfer.
- The holder remains the custody actor before preview or commit.
- The queued asset remains staged until preview and commit.

Where the operator slowed down:

- If the operator starts with the machine, the app still asks for holder and
  current location first.
- This is deliberate custody protection, but it is the most likely place field
  operators may feel friction.

Confusing labels or buttons:

- No asset-first implementation is justified from this scenario alone.
- A small future copy issue could make the ad hoc path clearer by saying:
  `Select who is receiving this asset, then scan it.`

### 3. Wrong-Holder Or Changed-Holder Correction Before Commit

Scenario: the operator realizes the selected holder is wrong before preview or
commit.

Expected operator path:

1. Use Change Holder from the Issue workflow banner or holder area.
2. Select the correct holder.
3. Return to Issue.
4. Review queue and preview before commit.

Result: PASS.

What worked:

- The Issue page exposes a Change Holder path through the workflow context.
- Holder selection returns to `/issue`.
- Queued assets remain staged; no custody event exists until commit.
- Preview repeats `Issue to` and the responsibility acknowledgment before the
  commit button.

Where the operator slowed down:

- If the operator notices the wrong holder only on preview, they must leave
  preview to change holder.
- That is acceptable because changing the custody actor is high gravity.

Confusing labels or buttons:

- `Change holder` is present and understandable.
- No route or behavior change is needed.

### 4. Missing Prerequisite Recovery

Scenario: the operator enters Issue without holder or location and must recover
without losing workflow intent.

Expected operator path:

1. Open Issue.
2. If no holder is selected, app redirects to holder search with
   `return_to=/issue`.
3. Select holder.
4. App returns to Issue.
5. If location is missing, the page shows Current Location and blocks scan with
   a clear message.
6. Save current location.
7. Continue to queue.

Result: PASS.

What worked:

- Missing holder redirects to `/holders?return_to=/issue`.
- Holder selection returns to `/issue`.
- Missing location is visible at the top of the Issue page.
- Scan submission without location is not added and reports the first location
  prerequisite error.
- Workflow intent remains Issue, not Return or generic preview.

Where the operator slowed down:

- The two prerequisites can feel like two separate gates.
- This is acceptable because holder and current location are both part of the
  custody record context.

Confusing labels or buttons:

- `Set where these assets are leaving from before scanning.` is clear enough for
  deployment.

### 5. Preview Confidence Check

Scenario: the operator confirms the preview clearly shows who accepts
responsibility and what machines will be issued.

Expected operator path:

1. Queue at least one asset.
2. Open Issue Preview.
3. Review Holder section.
4. Review Current Location section.
5. Review Assets section.
6. Review commit confirmations.

Result: PASS.

What worked:

- Preview shows `Issue to` with selected holder identity.
- Preview states: `Holder is the custody actor. Location and case/slot are
  context only.`
- Preview shows each asset tag and the issue result.
- Preview shows blocked item details before commit.
- Commit requires:
  - `I reviewed this batch and want to issue these assets to the selected
    holder.`
  - `I confirm the selected holder accepted responsibility for this issue
    batch.`

Where the operator slowed down:

- Preview uses a separate `Back to Batch Preview` local nav link, which may be
  slightly confusing because Issue Preview is the real workflow-specific review
  surface.
- This is a wording/navigation issue only, not a blocker to holder-first.

Confusing labels or buttons:

- Potential small copy/UI follow-up: make the Issue Preview back link more
  locally framed, such as `Back to Issue Queue`.

## What Worked

- Holder remains visible before scan, preview, and commit.
- Current location is collected before queue entries can be added.
- Queue is clearly staged and review-before-commit remains intact.
- Preview repeats the custody actor, location, assets, and responsibility
  acknowledgment.
- Missing prerequisites recover back into Issue instead of losing workflow
  intent.
- No scenario showed a need to weaken holder-first custody semantics.

## Where The Operator Slowed Down

- Single-machine ad hoc issue is the most awkward scenario because the operator
  may naturally start with a machine in hand.
- Holder and location are two separate prerequisites before scanning.
- Preview local navigation still has some generic wording inherited from batch
  preview.

## Any Confusing Labels Or Buttons

- `Review Before Issue` is clear.
- `Change holder` is clear.
- `Current Location` is clear enough.
- `Back to Batch Preview` on Issue Preview is the only notable copy/UI concern.

## Whether Asset-First Still Appears Necessary

No, not for deployment.

Asset-first staging may improve the single-machine ad hoc path, but it is not
necessary to answer the deployment custody question. The current holder-first
model better protects the proof that a specific holder accepted responsibility.

## Recommendation

Create a small copy/UI issue, not an asset-first staging issue.

Recommended decision:

```text
keep holder-first for deployment
```

Small follow-up, if desired:

```text
Issue follow-up: Tighten Issue Preview back-link and ad hoc scan guidance
```

Suggested scope:

- Rename Issue Preview local back link from `Back to Batch Preview` to
  `Back to Issue Queue`.
- Add or adjust one short Issue-page cue for ad hoc scans:
  `Select who is receiving this asset, set current location, then scan.`
- No route changes.
- No queue, preview, commit, custody, event, receipt, or schema changes.

Do not create a future asset-first staging issue unless live operator validation
shows repeated field failure with holder-first.

## Explicit Non-Changes Confirmation

This validation did not change:

- app behavior
- Issue routes
- Return routes
- holder selection
- location selection
- queue behavior
- preview behavior
- commit behavior
- custody logic
- event behavior
- receipt behavior
- schema or migrations
- dependencies
- tests
