# Issue 27-68 Workflow Cognition and Navigation Recon

## Scope and Guardrails

- Recon only. No UI, route, auth, workflow, or persistence changes were made.
- Required seam remains intact in code: `entry -> prerequisite -> queue -> preview -> commit`.
- Recon source was code inspection of `assettrack/intake/app.py` and intake templates.
- `PROJECT_MEMORY.md` and `CURRENT_STATE.md` were not present in the repo root during this session.

## Seam Validation

- `GET /issue` enforces holder selection before queue work and keeps current location as a prerequisite.
- `GET /issue/preview` and `POST /issue/commit` remain downstream of queue state.
- `GET /return` keeps queue before preview and `POST /return/commit` keeps commit behind explicit review.
- `GET /add-assets` and `POST /add-assets/review` keep stage queue before preview.
- No hidden redirect into preview was found in the inspected workflow templates.

Why it matters: consolidation can reduce clutter without changing operator state progression.

## Route Inventory

### Primary workflow routes

- `GET /dashboard`
- `GET /issue`
- `POST /issue/location`
- `GET /issue/preview`
- `POST /issue/commit`
- `GET /return`
- `GET /return/preview`
- `POST /return/commit`
- `GET /add-assets`
- `POST /add-assets/review`
- `GET /preview`
- `GET /preview/validate`
- `POST /preview/mode`
- `POST /preview/discard`
- `POST /preview/commit`

### Workflow prerequisite and lookup routes

- `GET /holders`
- `GET /holders/list`
- `GET /holders/<id>`
- `GET /holders/new`
- `POST /holders/new`
- `GET /holders/edit/<id>`
- `POST /holders/edit/<id>`
- `POST /holders/select`
- `POST /holders/clear`
- `POST /holders/<id>/toggle-active`
- `GET /assets/search`
- `GET /receipts`
- `GET /receipts/<id>`
- `POST /receipts/<id>/send`
- `GET /receipts/<id>/pdf`

### Admin surfaces

- `GET /admin/system`
- `GET /admin/users`
- `POST /admin/users/create`
- `POST /admin/users/<id>/toggle-active`
- `POST /admin/users/<id>/reset-password`
- `POST /admin/users/<id>/set-role`
- `GET|POST /admin/holders/import`
- `GET|POST /admin/reference-data`
- `GET /admin/db/export`
- `GET|POST /admin/db/restore`
- `GET /admin/report`
- `GET /admin/report/pdf`
- `GET|POST /admin/assets/new`
- `GET|POST /admin/assets/edit`
- `GET|POST /admin/assets/retire`
- `GET|POST /admin/assets/replace`
- `POST /admin/assets/create`
- `GET|POST /admin/assign-slot`
- `GET|POST /admin/slot-move`
- `GET|POST /admin/force-vacate`

### Report and drilldown surfaces

- `GET /report`
- `GET /dashboard/holders`
- `GET /dashboard/holders/<id>`
- `GET /dashboard/cases`
- `GET /dashboard/cases/<case_name>`

## Global Navigation Recon

### Current global nav

- `Dashboard`
- `Issue`
- `Return`
- `Holders`
- `Stage Assets` for admins
- `Admin Tools` for admins
- `Account`
- `Logout`

### Findings

- `Issue`, `Return`, and `Stage Assets` are all first-class entry points, but they expose overlapping queue-style workflow surfaces.
- `Holders` is both a general directory and an issue prerequisite, so it reads like a workflow tab even when it is support context.
- `Admin Tools` is only one of several admin destinations; admin report, asset edit, and restore also behave like secondary hubs.
- Global nav stays visible during preview and commit-adjacent screens, so high-gravity states still show multiple unrelated exits.

### Recommendation

- `KEEP`: `Dashboard`, `Issue`, `Return`, `Account`, `Logout`
- `DEMOTE`: `Holders` from global to contextual workflow/support navigation
- `DEMOTE`: `Stage Assets` from top-level tab to admin operations group
- `KEEP` but quiet: `Admin Tools` as the single admin hub entry

Why it matters: the top bar should express primary operator modes, not every reachable tool.

## Screen Inventory

### Dashboard

- Purpose: problem-first system overview and routing hub.
- Dominant action: review exceptions or move into the next operational surface.
- Secondary actions: search assets, open report, review cases, review holders.
- Duplicate controls: multiple links to report, holders, cases, and problems inside the same page.
- Verbosity concerns: repeated explanation around problem review and status overview.
- Cognition risks: the dashboard is both summary, launcher, and drilldown index, so action hierarchy blurs.
- Classification: `COLLAPSE` repeated status cards and `MERGE` repeated report/holder/case links into one launch area.

### Issue queue

- Purpose: issue workflow entry plus prerequisite capture plus queue management.
- Dominant action: add asset to queue.
- Secondary actions: save current location, jump to scan, jump to queue, clear queue, preview queue, back to dashboard.
- Duplicate controls: local navigation plus global `Issue` tab; jump links plus visible cards; queue clear appears again in preview.
- Verbosity concerns: repeated location guidance, scan blocking copy, workflow banner, and queue instructions.
- Cognition risks: prerequisite entry and queue action compete visually.
- Classification: `KEEP` prerequisite-first seam, `COLLAPSE` helper copy, `DEMOTE` jump links, `MERGE` queue actions into one area.

### Issue preview

- Purpose: intentional verification before commit.
- Dominant action: commit issue.
- Secondary actions: change holder, update current location, clear queue, back navigation.
- Duplicate controls: back to batch preview points to generic preview instead of issue queue; holder/location edits duplicate issue queue context.
- Verbosity concerns: holder and location cards restate data already implied by queue path.
- Cognition risks: preview exposes too many side exits for a high-gravity screen.
- Classification: `KEEP` preview and commit confirmation, `DEMOTE` side-edit links, `REMOVE` generic batch-preview back path in issue-specific context.

### Return queue

- Purpose: return workflow entry and queue management.
- Dominant action: add asset to queue.
- Secondary actions: clear queue, preview queue, back to dashboard, jump links.
- Duplicate controls: same queue controls as issue and stage assets; clear queue also appears elsewhere.
- Verbosity concerns: queue empty/help copy repeats scan intent.
- Cognition risks: queue actions are fragmented across multiple cards.
- Classification: `KEEP` queue and preview path, `MERGE` queue actions, `COLLAPSE` helper text, `DEMOTE` jump links.

### Return preview

- Purpose: intentional verification before return commit.
- Dominant action: commit return.
- Secondary actions: back to queue.
- Duplicate controls: blocked-items messaging is repeated at page top and inside asset rows.
- Verbosity concerns: before/after state labels repeat with little variation.
- Cognition risks: lower than issue preview; this is the calmest workflow screen.
- Classification: `KEEP` with only light compression.

### Stage Assets (`/add-assets`)

- Purpose: admin intake queue for adding inventory records.
- Dominant action: stage in queue.
- Secondary actions: clear queue, preview queue, optional case and slot tagging, back to return.
- Duplicate controls: same scan/queue pattern as return and issue; local back target is surprising.
- Verbosity concerns: latest scan, queue metadata, and next-step card all compete.
- Cognition risks: back link to `Return` suggests cross-workflow drift.
- Classification: `KEEP` admin-only flow, `REMOVE` misleading back-to-return link, `MERGE` shared queue affordance pattern with return/issue.

### Generic preview (`/preview`)

- Purpose: preview for add-assets workflow, with legacy issue-mode controls still present.
- Dominant action: add to database.
- Secondary actions: toggle issue mode, search/select holder, review issue details, back to dashboard.
- Duplicate controls: issue-specific controls inside non-issue preview; commit button label mutates by mode.
- Verbosity concerns: rows, status, commit, and issue-mode sections feel like two screens merged together.
- Cognition risks: this is the strongest workflow cognition break in the inspected UI.
- Classification: `MERGE` add-assets preview into stage-specific mental model, `REMOVE` legacy issue-mode controls from this surface in future cleanup.

### Holders search

- Purpose: holder directory plus issue prerequisite selection.
- Dominant action: search/select holder.
- Secondary actions: add holder, clear search, apply filter, clear selection, edit holder, issue assets.
- Duplicate controls: back to preview and `Issue Assets` are both shown; holder detail also allows selection.
- Verbosity concerns: selected-holder block and results table both repeat holder identity.
- Cognition risks: directory, maintenance, and issue prerequisite all compete.
- Classification: `KEEP` as prerequisite surface, `DEMOTE` maintenance actions, `REMOVE` duplicate workflow-entry links.

### Holder detail

- Purpose: inspect one holder and optionally select for issue.
- Dominant action: review assigned assets.
- Secondary actions: select holder, edit holder, activate/deactivate, back links.
- Duplicate controls: selection appears here and in search results.
- Verbosity concerns: summary cards and detail section are helpful; action row is the noisy part.
- Cognition risks: support page becomes alternate workflow entry.
- Classification: `KEEP` detail data, `DEMOTE` selection action unless entered from issue prerequisite flow.

### Asset search

- Purpose: support lookup and admin drill-in.
- Dominant action: search.
- Secondary actions: clear search, back to report, admin edit asset drilldown.
- Duplicate controls: search exists here and also implicitly on edit/retire asset admin screens.
- Verbosity concerns: acceptable.
- Cognition risks: low.
- Classification: `KEEP`.

### Receipts list and detail

- Purpose: receipt lookup, follow-up, and resend/retry visibility.
- Dominant action: search receipts or inspect one receipt.
- Secondary actions: back to dashboard/report, open current status report, download PDF, resend/retry.
- Duplicate controls: report entry reappears in receipts and receipt detail.
- Verbosity concerns: filters and status labels are mostly efficient.
- Cognition risks: receipt detail adds another report shortcut during a follow-up screen.
- Classification: `KEEP`, `DEMOTE` extra report shortcut on detail view.

### Report (`/report`)

- Purpose: read-only operational status with drilldowns.
- Dominant action: decide next support surface.
- Secondary actions: holders, cases, asset lookup, receipts, include retired toggle.
- Duplicate controls: same destinations appear in priority links, stat cards, and section drill links.
- Verbosity concerns: repeated “use this page to move to the next view” messaging.
- Cognition risks: report behaves like a second dashboard with its own launcher grid.
- Classification: `COLLAPSE` repeated launch areas, `KEEP` drilldowns, `MERGE` top launch links with summary stats.

### Dashboard holders and cases drilldowns

- Purpose: narrow dashboard/report detail views.
- Dominant action: inspect one holder or case.
- Secondary actions: back links.
- Duplicate controls: both expose `Back to Report` and `Back to Dashboard`, while details expose `Back to Cases` or `Back to Holders`.
- Verbosity concerns: low.
- Cognition risks: local back patterns are inconsistent but manageable.
- Classification: `KEEP`, `MERGE` back-pattern design.

### Admin tools hub

- Purpose: admin operations launcher and recovery-state overview.
- Dominant action: choose an admin tool.
- Secondary actions: download backup, acknowledge recovery.
- Duplicate controls: report and backup links reappear on report and restore screens.
- Verbosity concerns: restore-history and recovery-state explanations are reasonable.
- Cognition risks: launcher card plus action chip plus separate admin-only routes create admin hub drift.
- Classification: `KEEP` as sole admin hub, `MERGE` admin destinations here, `DEMOTE` direct top-level admin side paths elsewhere.

### Admin users

- Purpose: user creation and account maintenance.
- Dominant action: update or create user.
- Secondary actions: disable/enable, set role, generate temp password.
- Duplicate controls: several destructive/high-risk actions share equal visual weight.
- Verbosity concerns: one-time password helper is necessary; action stack is dense.
- Cognition risks: too many adjacent actions in each row.
- Classification: `KEEP`, `COLLAPSE` per-user actions into a revealed action area in future UI work.

### Admin report

- Purpose: read-only admin report and export surface.
- Dominant action: inspect report or export artifacts.
- Secondary actions: download PDF, download backup, back to admin tools.
- Duplicate controls: backup export appears here and on admin tools.
- Verbosity concerns: “report scope” is fine; full report is heavy but intentional.
- Cognition risks: report doubles as export launcher.
- Classification: `KEEP`, `DEMOTE` backup export from report header.

### Admin restore

- Purpose: validate and perform database restore.
- Dominant action: validate backup, then confirm replacement.
- Secondary actions: clear validation, back to admin tools.
- Duplicate controls: recovery instructions repeat admin tools context.
- Verbosity concerns: some instructional copy is required because of risk.
- Cognition risks: acceptable for a high-risk admin flow.
- Classification: `KEEP`.

### Admin holder import

- Purpose: CSV import for holders.
- Dominant action: upload CSV.
- Secondary actions: review result, back to admin tools.
- Duplicate controls: none significant.
- Verbosity concerns: low.
- Cognition risks: low.
- Classification: `KEEP`.

### Admin asset maintenance screens

- Included: new asset, edit asset, retire asset, replace asset, assign slot, slot move, force vacate.
- Purpose: focused admin maintenance workflows.
- Dominant action: each screen has one main maintenance action.
- Secondary actions: back to dashboard, occasional cross-links to other admin asset actions.
- Duplicate controls: many screens use dashboard as the only back target instead of admin hub; edit links to retire, new links to edit, asset search links into edit.
- Verbosity concerns: step numbering helps on multi-step screens; repeated lookup instructions can be reduced.
- Cognition risks: admin asset tasks feel like isolated routes instead of one admin maintenance cluster.
- Classification: `KEEP`, `MERGE` under one admin-maintenance navigation model, `DEMOTE` cross-links that bypass the hub.

## Navigation Hierarchy Proposal

### Global nav

- `Dashboard`
- `Issue`
- `Return`
- `Admin Tools` for admins only
- `Account`
- `Logout`

### Workflow-local nav

- Issue:
  `Select Holder` -> `Set Current Location` -> `Queue` -> `Preview` -> `Commit`
- Return:
  `Queue` -> `Preview` -> `Commit`
- Stage Assets:
  `Queue` -> `Preview` -> `Commit`

### Quiet navigation approach

- Keep one local back path per screen.
- Hide unrelated launcher links on preview and commit-adjacent screens.
- Use workflow banner/context banner for state, not for route launching.
- Reserve global nav for mode changes, not step changes.

### Expandable-section opportunities

- Dashboard status sections already use `details`; repeated summary areas can collapse further.
- Report sections already use `details`; top priority launch grid can collapse into one expandable “Next Actions” area.
- Admin per-user action stacks are good candidates for contextual reveal.
- Holder detail secondary metadata can stay collapsed behind identity and assets.

### Destructive/admin action placement

- Keep destructive admin actions inside admin-only flows.
- Move direct admin asset cross-links behind a single admin maintenance hub or grouped local nav.
- Keep export/restore separated from read-only report browsing.

Why it matters: calmer navigation preserves deterministic workflow state and reduces accidental context switching.

## Consolidation Candidates

### Repeated workflow paths

- Holder selection is reachable from holders search, holder detail, generic preview, and issue preview.
- Report entry appears from dashboard, receipts, receipt detail, and report-adjacent screens.
- Admin backup export appears from admin tools and admin report.
- Admin dashboard back-links are repeated across nearly every admin screen.

### Duplicate buttons and links

- `Clear queue` exists on issue queue, return queue, issue preview, and stage assets.
- `Preview Queue` exists on return queue and stage assets; issue preview path is split across issue workflow.
- `Back to Dashboard` appears on nearly every support screen even when a more local parent exists.
- `Change holder` and `Select holder` duplicate the prerequisite route.

### Repeated helper text

- Scan instructions repeat across issue, return, and stage assets.
- Preview review/commit confirmation copy repeats across issue and return.
- Report and dashboard both explain “what to do next” in multiple places.
- Admin lookup screens repeat “search, then select” explanations.

### Repeated action rows

- Dashboard repeats launch links in hero, cards, and collapsible sections.
- Report repeats the same destinations in the top link row and stat tiles.
- Admin users repeats several equal-weight actions per user row.

## Safe Compression Opportunities

### KEEP

- Explicit preview screens.
- Commit confirmation checkboxes.
- Holder prerequisite before issue.
- Current location prerequisite before issue scans.
- Recovery and restore instruction depth on admin safety surfaces.

### COLLAPSE

- Dashboard repeated summary and launcher content.
- Report top launch areas.
- Admin user action stacks.
- Non-critical holder metadata and helper copy.

### MERGE

- Queue action layout across issue, return, and stage assets.
- Report launcher links and report summary stats.
- Admin maintenance screens into one coherent admin-maintenance navigation family.
- Back-link behavior across dashboard/report drilldowns.

### DEMOTE

- `Holders` from global nav to support/prerequisite context.
- `Stage Assets` from top nav to admin tools context.
- Report shortcuts on receipt detail and other support screens.
- Change-holder and update-location links on issue preview.

### REMOVE

- Generic issue-mode controls from `/preview` once that cleanup issue is approved.
- `Back to Return` on the stage-assets screen.
- Duplicate workflow-entry links on holders search.
- Repeated launch links that restate the same destination within one screen.

## Prioritized Next-Step Recommendations

1. Fix workflow-entry hierarchy first: reduce global nav to true modes and remove misleading local back targets.
2. Simplify `/preview`: separate add-assets preview from legacy issue-mode controls.
3. Compress queue screens into one repeated pattern with one dominant action and one next-step action.
4. Collapse dashboard and report launcher duplication so each surface has one action cluster.
5. Consolidate admin maintenance navigation under the admin hub before touching individual admin forms.

Why it matters: these steps reduce operator cognition cost without altering workflow behavior or event semantics.

## Verification

- No templates changed.
- No routes changed.
- No auth behavior changed.
- No persistence behavior changed.
- No workflow behavior changed.
