# Issue 27-73 Recon: Workflow Surface Compression

## Scope

Recon only.

- No template, route, CSS, auth, schema, persistence, or workflow behavior changes.
- Focus: where current workflow and admin surfaces can be compressed later without weakening clarity or the queue -> preview -> commit seam.

## Sources Reviewed

- `AGENTS.md`
- `assettrack/intake/app.py`
- `assettrack/intake/templates/base.html`
- `assettrack/intake/templates/index.html`
- `assettrack/intake/templates/preview.html`
- `assettrack/intake/templates/issue_preview.html`
- `assettrack/intake/templates/return_queue.html`
- `assettrack/intake/templates/return_preview.html`
- `assettrack/intake/templates/admin_system.html`
- `assettrack/intake/templates/admin_reference_data.html`
- `assettrack/intake/templates/admin_users.html`
- `assettrack/intake/templates/admin_holder_import.html`
- `assettrack/intake/templates/admin_human_report.html`

## Current Surface Inventory

### Operator workflow surfaces

- `Add Assets`:
  Purpose: admin-only asset creation entry with queue, optional case/slot assignment, and preview handoff.
  Evidence: `index.html`, `app.py:add_assets` and `app.py:add_assets_review`.

- `Preview`:
  Purpose: batch review for staged asset creation, plus legacy issue-mode toggle and holder shortcut links.
  Evidence: `preview.html`, `app.py:preview`, `app.py:preview_mode`, `app.py:preview_commit`.

- `Issue`:
  Purpose: direct workflow page for issue operations. Requires holder selection, current location selection, scan queue management, and preview handoff.
  Evidence: `app.py:issue` renders `return_queue.html` with issue-specific context.

- `Issue Preview`:
  Purpose: final issue review of holder, current location, asset state transitions, blocking issues, and commit acknowledgment.
  Evidence: `issue_preview.html`, `app.py:issue_preview`, `app.py:issue_commit`.

- `Return`:
  Purpose: direct workflow page for return scanning, queue management, blocking issue review, and preview handoff.
  Evidence: `return_queue.html`, `app.py:return_queue`.

- `Return Preview`:
  Purpose: final return review of state transitions, blocking issues, and commit acknowledgment.
  Evidence: `return_preview.html`, `app.py:return_preview`, `app.py:return_commit`.

### Shared navigation surface

- `Primary top navigation`:
  Purpose: global movement between Dashboard, Issue, Return, Reports, and Admin destinations.
  Evidence: `base.html:45-80`.

### Admin surfaces

- `Admin Tools`:
  Purpose: admin landing page for maintenance destinations, recovery state, system snapshot, and restore history.
  Evidence: `admin_system.html`, `app.py:admin_system`.

- `Admin Reference Data`:
  Purpose: create organizations, create buildings, and map organizations to buildings.
  Evidence: `admin_reference_data.html`, `app.py:admin_reference_data`.

- `Admin Users`:
  Purpose: create users, inspect account state, change role, enable/disable accounts, and generate temporary passwords.
  Evidence: `admin_users.html`, `app.py:admin_users`.

- `Admin Holder Import`:
  Purpose: upload holder CSV and review import summary/errors.
  Evidence: `admin_holder_import.html`, `app.py:admin_holder_import`.

- `Admin Current Status Report`:
  Purpose: read-only operational report with PDF and DB backup actions.
  Evidence: `admin_human_report.html`, `app.py:admin_human_report`.

## Compression Candidates

### Candidate 1

surface:
global navigation in `base.html`

current issue:
Top-level navigation already compresses admin links into a details menu, but the same destinations also reappear as repeated local "Back to ..." links on every page. This creates stacked navigation layers on small screens and competes with the first actionable workflow control.

why it matters:
Operators under time pressure should see one obvious next action, not both global and local navigation competing at the top of the screen.

safe compression option:
Demote repeated local back-links into a shared, quieter page utility pattern or show them only where the global nav does not already provide an equivalent safe escape route.

risk:
If over-compressed, users may lose orientation when arriving from non-linear paths like holder search, report drill-downs, or admin subpages.

recommended action:
Open a Class 1 issue to inventory all local back-links and collapse only duplicates of already-visible global destinations. Keep unique path-specific return links.

### Candidate 2

surface:
`Add Assets` entry surface in `index.html`

current issue:
The page shows lock state, unlock instructions, a separate lock link, queue entry controls, queue contents, preview handoff, and a standalone "Latest" card. The "Latest" card repeats information already visible in the queue when the queue is non-empty.

why it matters:
This page is an entry surface. Extra status blocks and trailing cards dilute the core sequence: select metadata -> scan -> preview.

safe compression option:
Demote the standalone "Latest" card into the queue header or remove it when queue contents are already visible. Group lock/unlock status into a tighter entry-status strip rather than separate paragraphs.

risk:
If lock state gets hidden too aggressively, the operator may miss why scan entry is unavailable.

recommended action:
Open a Class 1 issue to compress entry-only chrome on `Add Assets` while preserving visible locked/unlocked state and keeping preview as a separate next step.

### Candidate 3

surface:
general `Preview` page in `preview.html`

current issue:
The page mixes two roles: add-assets batch preview and issue-mode control center. The commit card and issue-mode card compete visually, and the issue-mode card introduces alternative navigation from within preview.

why it matters:
Preview should read as a review checkpoint, not a branching hub. Mixed intent weakens preview clarity and makes operator next action less obvious.

safe compression option:
Demote the issue-mode controls into a smaller secondary section or move them behind a collapsed "Issue workflow options" affordance in a later implementation issue, while keeping preview itself read-only plus commit-focused.

risk:
If the issue-mode toggle or holder shortcut becomes too hidden, admins may struggle to discover the issue workflow from legacy paths.

recommended action:
Open a Class 1 issue to reduce the visual weight of issue-mode controls on `Preview` without removing the current route or changing the underlying mode behavior.

### Candidate 4

surface:
issue workflow entry in `return_queue.html` as rendered by `app.py:issue`

current issue:
The issue flow uses the return queue template, which is efficient from a code reuse perspective, but the page still presents multiple message zones, a jump-to-scan link, a current-location card, a scan card, optional blocked-items card, preview card, and queue card. Some state is explained twice: current location required, scanning blocked until current location is set, and location errors.

why it matters:
Issue is the most cognitively dense workflow. Duplicate explanation increases read burden before scanning can begin.

safe compression option:
Collapse current-location helper copy into one status line plus errors, and show only one of: requirement text, blocked warning, or success flash for location. Keep the location form as a distinct prerequisite card.

risk:
If prerequisite language becomes too short, operators may miss that current location is mandatory before scan entry.

recommended action:
Open a Class 1 issue to compress issue prerequisite messaging only. Do not merge the location and scan cards, and do not let preview become the entry point.

### Candidate 5

surface:
issue workflow preview in `issue_preview.html`

current issue:
Holder, current location, blocked items, asset-state table, and commit controls are all surfaced at full weight. Both page banner and cards repeat queued-state context. Per-row before/after state is necessary, but the page also carries repeated action links like "Change holder" and "Update current location."

why it matters:
This is the last safety checkpoint before commit. It needs high signal, but not every helper action needs equal emphasis.

safe compression option:
Demote edit links for holder/current location into a quieter shared review-actions strip. Keep the holder card, location card, blocked-items card, and asset diff table visible.

risk:
If holder or location summaries are collapsed too far, the operator may miss who is accepting custody or where assets are being issued.

recommended action:
Open a Class 1 issue to reduce secondary-action prominence on issue preview while leaving all review facts fully visible.

### Candidate 6

surface:
return workflow entry in `return_queue.html` as rendered by `app.py:return_queue`

current issue:
The page is cleaner than issue mode, but still spreads action across global flashes, optional recent-case verification flash, workflow banner, scan card, blocked-items card, preview card, and queue card. The preview action sits in its own card with little supporting context.

why it matters:
Return should feel linear. Extra card boundaries make the page read longer than the workflow actually is.

safe compression option:
Fold the preview handoff into the queue card footer or scan/queue stack while keeping it visually distinct as the next step after queue review.

risk:
If the preview action is merged too tightly into scan controls, users may mistake preview for a scan-side action and skip queue review.

recommended action:
Open a Class 1 issue to compress card count on the return entry page while keeping the order: scan -> queue -> preview.

### Candidate 7

surface:
return workflow preview in `return_preview.html`

current issue:
The preview page is comparatively focused, but still duplicates state with a banner, readiness card, blocked-items card, asset table, and commit card. The computed `blocked_count` is unused, which suggests intended summary compression that never happened.

why it matters:
This page is close to the right density already. Small compression gains are possible without touching behavior.

safe compression option:
Merge readiness and blocked summary into a single review-summary card above the asset table. Keep asset table and commit card unchanged.

risk:
If blocked details move below the fold or lose prominence, conflict resolution could be delayed.

recommended action:
Open a small Class 1 issue to unify the top-of-page summary only.

### Candidate 8

surface:
`Admin Tools` in `admin_system.html`

current issue:
The page is both a launcher and a status dashboard. It shows recovery state, six primary admin destinations, DB export, system snapshot, and restore history together. Recovery state is rendered in two variants, active and inactive, which adds structural weight even when inactive.

why it matters:
Admins need one obvious action cluster first, then system facts. Mixed priority makes the page feel busier than it is.

safe compression option:
Keep recovery-active state prominent, but collapse inactive recovery state and restore history behind optional disclosure in a future UI issue. Keep launch actions above diagnostics.

risk:
If restore state/history is hidden too aggressively, recovery readiness may be missed during operational follow-up.

recommended action:
Open a Class 1 issue to separate "launch tools" from "system diagnostics" visually, with inactive diagnostics demoted but not removed.

### Candidate 9

surface:
`Admin Reference Data` in `admin_reference_data.html`

current issue:
Three create/manage tasks are stacked with full tables always visible. Organizations, buildings, and mappings all compete for attention even though most admins likely perform one task at a time.

why it matters:
This page is not operator-facing, but it still carries unnecessary scan burden and visible controls.

safe compression option:
Convert each section into an expandable card later, defaulting open for the form most recently used or the first empty dataset.

risk:
If all sections default collapsed, discoverability may drop for infrequent admins.

recommended action:
Open a Class 1 issue for expandable section treatment on reference data only. No route or form changes.

### Candidate 10

surface:
`Admin Users` in `admin_users.html`

current issue:
Create-user form and full user action matrix are both always expanded. In the users table, enable/disable, set role, and temporary password generation all have equal visual weight, including warning-styled reset controls inside every row.

why it matters:
This is a high-risk admin surface. Too many equally prominent controls increase accidental action risk.

safe compression option:
Keep account state obvious, but demote secondary actions into an expandable per-row action area or split primary action from advanced actions visually.

risk:
Compression must not obscure account state or hide the one-time temporary password warning after generation.

recommended action:
Open a Class 1 issue to reduce visible per-row control density while preserving explicit state chips and one-time password disclosure.

### Candidate 11

surface:
`Admin Holder Import` in `admin_holder_import.html`

current issue:
This page is already compact. The only repeated state is the flash summary plus the persistent result card after import.

why it matters:
This is a low-value target for compression effort.

safe compression option:
If changed later, unify result summary and flash into one result surface after POST.

risk:
Low.

recommended action:
Do not prioritize. Leave unchanged unless a broader admin consistency pass happens.

### Candidate 12

surface:
`Admin Current Status Report` in `admin_human_report.html`

current issue:
The page exposes many full-width tables and two download actions at the top. It is intentionally dense, but some sections are reference-heavy rather than immediately actionable.

why it matters:
This page serves audit and operational review. Over-compressing it would hurt scanability for investigations, but selective section folding could help routine use.

safe compression option:
Keep top summary and assets/current custody visible. Make lower-value sections like organization-building mappings or case totals collapsible in a future admin-only presentation issue.

risk:
This report is read-only but operationally important. Hidden sections can reduce confidence during reconciliation or recovery review.

recommended action:
Open a cautious Class 1 issue only if the team wants admin-report section folding. Lower priority than workflow surfaces.

## Do-Not-Change List

- Do not compress the direct `/issue` entry route into `/issue/preview`.
  Why: `app.py:4391-4460` keeps issue entry on its own page and preserves prerequisite -> queue -> preview order.

- Do not compress the direct `/return` entry route into `/return/preview`.
  Why: `app.py:4638-4674` keeps scan/queue work on the workflow page before preview.

- Do not remove or hide the current-location prerequisite card on issue entry.
  Why: current location is validated before issue scans and commit (`app.py:4408-4415`, `4465-4492`, `4587-4595`).

- Do not collapse blocked-items visibility below the fold on issue or return preview.
  Why: blocked state protects commit safety and reconciliation clarity.

- Do not merge queue and commit controls onto one page section that weakens the preview checkpoint.
  Why: the required seam is queue -> preview -> commit.

- Do not demote holder identity below immediate visibility on issue preview.
  Why: holder selection is part of custody responsibility review.

- Do not compress recovery-active messaging on admin surfaces.
  Why: recovery mode gates receipt-related actions and requires acknowledgment (`base.html:83-103`, `admin_system.html:81-132`).

- Do not remove one-time temporary password disclosure from admin users.
  Why: it is operationally sensitive and must remain explicit (`admin_users.html:60-69`).

## Recommended Follow-On Issues

### Follow-On 1

title:
Compress duplicate navigation and helper chrome across workflow pages

classification:
Class 1

purpose:
Reduce repeated back-links, repeated helper copy, and low-value status blocks without changing route flow.

scope:
`base.html`, `index.html`, `return_queue.html`, `preview.html`, `issue_preview.html`, `return_preview.html`

non-goals:
No route changes. No auth/lock behavior changes. No preview seam changes.

risk level:
Medium

### Follow-On 2

title:
Reduce issue workflow prerequisite message duplication

classification:
Class 1

purpose:
Make issue entry read more linearly by compressing current-location requirement copy and message stacking.

scope:
Issue mode rendering inside `return_queue.html` only.

non-goals:
Do not merge prerequisite and scan sections. Do not allow scanning before current location is valid.

risk level:
High

### Follow-On 3

title:
Demote issue-mode controls on generic preview

classification:
Class 1

purpose:
Make `Preview` read as a review checkpoint first and an issue-mode control surface second.

scope:
`preview.html` only

non-goals:
No issue-mode behavior changes. No holder-selection flow changes.

risk level:
Medium

### Follow-On 4

title:
Compress return entry card count while preserving scan -> queue -> preview order

classification:
Class 1

purpose:
Reduce visual fragmentation on return entry.

scope:
Return-mode rendering in `return_queue.html`

non-goals:
No preview route changes. No queue logic changes.

risk level:
Medium

### Follow-On 5

title:
Demote secondary edit links on issue preview

classification:
Class 1

purpose:
Keep review facts dominant and reduce competing holder/location edit actions.

scope:
`issue_preview.html`

non-goals:
No change to visible review facts, commit acknowledgments, or blocked item logic.

risk level:
Medium

### Follow-On 6

title:
Separate admin launch actions from diagnostics on Admin Tools

classification:
Class 1

purpose:
Make the admin landing page easier to scan by prioritizing actionable destinations over diagnostics.

scope:
`admin_system.html`

non-goals:
No restore or recovery behavior changes. No removal of recovery-active messaging.

risk level:
Medium

### Follow-On 7

title:
Add expandable sections to admin reference data

classification:
Class 1

purpose:
Reduce always-visible admin form density on a non-operator page.

scope:
`admin_reference_data.html`

non-goals:
No CRUD changes. No new dependencies.

risk level:
Low

### Follow-On 8

title:
Reduce per-row action density on admin users

classification:
Class 1

purpose:
Lower accidental-action risk by separating primary user state from advanced row controls.

scope:
`admin_users.html`

non-goals:
No role/auth logic changes. No temporary password flow changes.

risk level:
High

## Priority Order

1. Compress duplicate navigation and helper chrome across workflow pages.
2. Reduce issue workflow prerequisite message duplication.
3. Demote issue-mode controls on generic preview.
4. Compress return entry card count while preserving scan -> queue -> preview order.
5. Demote secondary edit links on issue preview.
6. Separate admin launch actions from diagnostics on Admin Tools.
7. Reduce per-row action density on admin users.
8. Add expandable sections to admin reference data.

Reason for order:

- Workflow-facing compression comes first because operator cognitive load matters more than admin convenience.
- Issue surfaces come before return surfaces because issue currently carries the heaviest prerequisite and summary burden.
- Admin changes come after workflow surfaces because they are lower-frequency and easier to stage cautiously.

## Operator Smoke-Test Implications

Future manual operator smoke testing is required for any follow-on issue that touches:

- `index.html`
- `preview.html`
- `return_queue.html`
- `issue_preview.html`
- `return_preview.html`
- `base.html` if primary navigation or workflow escape routes change visually

Minimum manual smoke test for those follow-on issues:

1. Login.
2. Enter issue workflow directly from primary navigation.
3. Verify prerequisite selection remains before queue activity.
4. Scan into queue.
5. Verify preview remains a distinct step.
6. Verify commit remains unavailable or blocked until review conditions are met.
7. Repeat for return workflow.
8. Confirm queue clears only after commit or explicit clear action.

Admin-only presentation follow-ons should still get manual review, but they do not require full operator workflow smoke testing unless shared navigation or shared page chrome changes.

## Highest-Risk Compression Areas

- Issue entry prerequisite messaging:
  Risk: easy to hide required current-location context.

- Generic preview issue-mode controls:
  Risk: easy to turn preview into a branching control surface or weaken review focus.

- Admin users action density:
  Risk: easy to hide high-consequence controls or make accidental actions more likely.

## Bottom Line

The safest near-term compression opportunities are not page merges. They are reductions in duplicated helper text, duplicated navigation, duplicated status summaries, and overly prominent secondary actions.

The surfaces that should remain structurally intact are the issue and return workflow entry pages, both preview pages, the issue current-location prerequisite, blocked-items visibility, and recovery-active messaging.
