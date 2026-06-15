# Issue 27-169: Minimalist Application Copy And Navigation Model

## 1. Executive Recommendation

AssetTrack can remove a large share of nonessential operator-facing presentation load without changing custody truth, workflow order, route behavior, role enforcement, receipt truth, recovery behavior, schema, or persistence.

The safe direction is not a broad rewrite. The safe direction is a phased presentation-only cleanup that applies this rule consistently:

> Say it once, place it where the operator needs it, and link to it elsewhere when repetition adds no operational value.

The strongest reduction opportunities are:

- Remove or shorten helper paragraphs that restate nearby headings or controls.
- Consolidate repeated local navigation where global navigation or workflow context already gives the same route.
- Move supporting explanation out of primary action cards when the operator does not need it to complete the action.
- Show warnings only when the warned condition exists, except recovery, permission, destructive, receipt-delivery-failure, and custody-proof warnings.
- Keep all workflow prerequisites, queue state, preview contents, commit target, and commit consequences visible.

The application can likely remove about one third of current counted presentation load across the reviewed surfaces. A true 50% reduction is realistic only if measured against nonessential presentation load, not against all visible operational state and warnings.

## 2. Is The 50% Reduction Target Realistic?

Yes, for nonessential presentation load. No, not as a blanket reduction of all visible content and actions.

Current reviewed estimate:

- Visible content items: about 239.
- Action/navigation items: about 118.
- Total counted load: about 357.

Proposed reviewed estimate:

- Total counted load: about 247.
- The proposed content/action split varies by phase; section 20 gives the weighted application-wide model.

Estimated application-wide reduction:

- Total visible presentation load: about 31%.
- Nonessential presentation load only: about 55% to 60%.
- Confidence: medium.

Why the full 50% target should not be forced:

- Workflow prerequisites must remain visible before action.
- Queue and preview state must remain visible.
- Commit consequences and acknowledgment text must remain visible.
- Receipt proof, delivery failure truth, missing custody proof, conflicting custody state, recovery warnings, permission denial, destructive admin warnings, and irreversible consequences must remain visible.

Plain statement: approximately 50% reduction is realistic as a planning target for unnecessary presentation load, but not as a target for every visible application surface.

## 3. Definition Of Presentation Load

For this recon, presentation load means visible operator-facing or admin-facing UI burden from:

- instructional text
- repeated explanations
- duplicate navigation
- duplicate actions
- competing page choices
- descriptions that repeat headings or controls
- supporting information shown before it is needed
- warnings displayed when their triggering condition is absent

It does not mean:

- source-code size
- network performance
- rendering performance
- dependency count
- schema size
- data-table row count
- custody/event/receipt history volume

## 4. Counting And Estimation Method

Counting rules used:

- Count each visible paragraph or independent helper-text block as one content item.
- Count each warning, flash, status explanation, or static status block as one content item.
- Count each button or actionable link as one action.
- Count repeated global navigation once in shared navigation.
- Do not count table rows, asset rows, holder rows, receipt rows, or other variable records.
- Do not count required field labels as removable content.
- Count uncertain surfaces as ranges and use midpoint estimates for application totals.

Confidence scale:

- High: direct template inspection with stable visible blocks and actions.
- Medium: direct template inspection, but conditional branches or variable blocks make counts approximate.
- Low: broad surface grouped from several related templates.

The counts are planning estimates, not test metrics.

Future implementation issues should use the counts to define direction and review scope, not as pass/fail acceptance thresholds. An implementation may retain more content when manual smoke testing shows that removal would weaken operator clarity.

## 5. Application-Wide Minimalist Standards

Recommended standards for future implementation issues:

- One page, one dominant primary action.
- Preserve local workflow navigation only when it preserves workflow intent or safe `return_to`.
- Do not place a paragraph after a heading when it repeats the heading.
- Do not explain controls whose labels and immediate context already explain the action.
- Put prerequisite state before scan, preview, or commit actions.
- Put destructive, irreversible, or recovery warnings directly beside the action.
- Put receipt-delivery failure truth directly beside receipt delivery actions and failed delivery status.
- Link to supporting reports when the operator does not need the detail to complete the current action.
- Keep error, permission, recovery, custody-proof, conflict, and validation messages explicit.
- Standardize equivalent workflow copy between Issue and Return.

## 6. Shared-Navigation Findings

Surfaces inspected:

- `base.html`
- `_workflow_context_banner.html`
- `_timeout_status.html`
- page-level `workflow-local-nav` blocks across operator and admin templates
- 403 and 404 pages

Operational purpose:

- Provide stable primary routes, role-appropriate admin access, account/logout access, recovery state, and workflow context.

Primary operator action:

- Move to the next relevant operational surface without losing workflow intent.

Visible items reviewed:

- Global nav: Dashboard, Issue, Return, Holders, Reports.
- Admin nav panel: Admin Tools, Users, Reference Data, Import Holders, Operational Report, Restore Database.
- Utility nav: Account, Logout.
- Recovery mode banner with admin review link.
- Workflow context banner with holder/destination/queue summary and Change Holder action.
- Repeated local Back links on many pages.
- 403/404 safe-next-step paragraphs and safe-page links.

Required items:

- Global workflow destinations: Keep visible. They prevent dead ends under field pressure.
- Admin menu only for admins: Keep visible. It protects role boundaries.
- Account/Logout: Keep visible. They protect local auth/account workflow.
- Recovery mode banner: Do not change except by separate recovery issue. It protects recovery-mode restrictions and receipt resend blocking.
- Workflow context banner state: Keep visible. It protects custody actor, destination holder, queue count, and workflow intent.
- 403 permission denial: Keep visible. It protects local role enforcement clarity.

Nonessential items:

- Repeated "Back to Dashboard" on pages already reachable from global Dashboard: Consolidate.
- Repeated "Back to Admin Tools" on every admin page while Admin menu is present: Consolidate or standardize.
- 404 second paragraph can be shortened: Shorten.
- Duplicate mobile and desktop Change Holder link inside workflow banner can be standardized by layout, not duplicated semantically: Standardize.

Recommended simplified model:

- Keep global nav, admin menu, utility nav, recovery banner, permission denial, and workflow context.
- Keep local Back links only when `return_to` preserves workflow or report drilldown context.
- Prefer one contextual Back link, not both local and global equivalents.

Estimate:

| Surface | Current content | Current actions | Proposed content | Proposed actions | Reduction | Confidence |
|---|---:|---:|---:|---:|---:|---|
| Shared navigation and shared warnings | 12 | 20 | 8 | 14 | 31% | Medium |

## 7. Operator-Surface Findings

Operator surfaces inspected:

- `dashboard.html`
- `return_queue.html` for Issue and Return queue rendering
- `issue_preview.html`
- `return_preview.html`
- `preview.html`
- `holders_search.html`
- `holder_detail.html`
- `holder_new.html`
- `holder_edit.html`
- `asset_search.html`
- `receipt_detail.html`
- `receipts_list.html`
- `report_readonly.html`
- `dashboard_cases.html`
- `dashboard_case_detail.html`
- `dashboard_holders.html`
- `dashboard_holder_detail.html`

Main finding:

The operator side has the right custody and workflow state, but too many supporting sentences compete with the next action. Issue and Return are mostly safe to simplify by removing repeated helper copy while preserving prerequisites, queue, preview, and commit confirmations.

Largest operator reductions:

- Dashboard orientation copy can be shorter.
- Issue queue repeats holder/current-location/queue instructions in multiple places.
- Return queue repeats queue/review guidance.
- Issue preview duplicates holder and current-location concepts already shown at entry.
- Report pages have many alternate drilldown links and explanatory labels before need.
- Holder pages repeat "person or group" guidance.
- Receipt list and receipt detail can keep proof/failure state while linking secondary metadata.

## 8. Admin-Surface Findings

Admin surfaces inspected:

- `admin_system.html`
- `admin_reference_data.html`
- `admin_users.html`
- `admin_holder_import.html`
- `admin_new_asset.html`
- `admin_edit_asset.html`
- `admin_retire_asset.html`
- `admin_replace_asset.html`
- `admin_slot_provision.html`
- `admin_assign_slot.html`
- `admin_slot_move.html`
- `admin_force_vacate.html`
- `admin_receipt_cc.html`
- `admin_human_report.html`
- `admin_db_restore.html`
- admin route flashes and redirects in `app.py`

Main finding:

Admin pages contain more text that must remain than operator pages because the actions can change access, recovery state, slot state, asset records, or database state. The safe reduction is mostly in repeated navigation and paragraphs that restate form labels. Destructive warnings and recovery guidance should not be reduced aggressively.

Largest admin reductions:

- Admin Tools duplicates the admin menu.
- Reference Data helper paragraphs restate headings and form labels.
- Holder import can shorten import mechanics while keeping required columns.
- User administration can reduce per-row action density but must keep temp-password one-time warning.
- Admin report can link to backup instead of repeating backup caveat inline.
- Restore must keep validation, replacement, rollback, recovery, and custody-event boundaries visible.

## 9. Page-By-Page Current And Proposed Models

### Shared Shell

- Page purpose: app-wide routing and role context.
- Required visible state: current route, role-appropriate admin access, recovery mode.
- Primary action: move to the next operational surface.
- Secondary actions: Account, Logout.
- Point-of-action guidance: none needed except recovery banner.
- Conditional warnings: recovery mode only when active; permission denial on 403.
- Supporting links: Admin Tools only when admin; Review Recovery State only when active.
- Content removed or consolidated: repeated local links that duplicate global navigation.

### Dashboard

- Page purpose: operational status and next action.
- Primary operator action: choose Issue, Return, current custody, case status, or asset search.
- Visible items: read-only custody map note, Issue/Return action cards, Assets Out, Assets Remaining, Total Assets, map intro, empty-map note, case/status tables.
- Required: dashboard counts, custody map read-only boundary, Issue/Return entry actions.
- Nonessential: map intro duplicates read-only note; "Open Issue Workflow" and "Issue Assets" duplicate each other; "Open Return Workflow" duplicates "Return Assets."
- Simplified page: status counters plus Issue and Return as dominant actions; one read-only custody-map note; drilldowns remain.
- Estimate: current content 8, actions 8; proposed content 5, actions 6; reduction 31%; confidence medium.

### Issue Entry And Prerequisite Selection

- Page purpose: choose receiving holder and current location before scanning.
- Primary action: set valid current location, then scan.
- Visible items: workflow banner, Current Location card, building/room controls, current-location status, organization-limit note, validation messages, Add to Queue card, receiving-holder summary.
- Required: receiving holder, organization if different from holder name, current building/room, validation messages, queue count.
- Nonessential: "Select who is receiving the asset, set current location, then scan. Staged scans stay in the queue until review." repeats the visible cards and preview button.
- Simplified page: workflow banner, current location controls/status, scan input, queue state. One short prerequisite line only when location or holder is missing.
- Estimate: current content 11, actions 6; proposed content 7, actions 5; reduction 29%; confidence high.

### Issue Scan Queue

- Page purpose: stage assets for issue after holder and location are valid.
- Primary action: Add to queue.
- Visible items: scan input, Add to queue, Clear queue, Review Before Issue, Queue count, queued items with remove buttons, blocked items.
- Required: scan input, queue count, queued asset identity, remove, clear queue confirmation, blocked items.
- Nonessential: repeated queue staging explanations when queue and preview controls are visible.
- Simplified page: scan input and Add to queue are dominant; Review Before Issue remains secondary until queue has items; Clear queue remains secondary and danger-styled.
- Estimate: current content 8, actions 7; proposed content 5, actions 6; reduction 27%; confidence high.

### Issue Preview

- Page purpose: review holder, current location, assets, blocked items, and commit consequences before custody events are appended.
- Primary action: Commit Issue.
- Visible items: Back to Issue Review link, workflow banner, Ready/Needs Review, Holder card, holder guidance, Current Location card, organization-limit note, Blocked Items, Assets, Commit intro, responsibility acknowledgment, Commit Issue, Clear Queue.
- Required: custody actor, organization context, current location, queued asset identity, before/after custody/location state, blocked items, acknowledgment, commit target, commit consequence.
- Nonessential: "Holder is the custody actor. Location and case/slot are context only." is operationally useful but longer than necessary and repeated across the workflow.
- Simplified page: retain the custody-actor fact in shorter standardized wording, then show one review-status block, holder/current-location summary, asset review, and commit acknowledgment. Keep Clear Queue lower priority.
- Guardrail: do not replace this fact with a repository-document link. A link is acceptable only if a separately approved issue creates an offline in-app destination that preserves queue and workflow state.
- Estimate: current content 16, actions 5; proposed content 11, actions 4; reduction 29%; confidence high.

### Issue Commit Result

- Page purpose: confirm issue completion and receipt proof.
- Primary action: review receipt detail.
- Visible items: success flash, receipt detail page, delivery actions/status.
- Required: committed count, receipt proof, delivery state.
- Nonessential: none in the commit redirect itself.
- Simplified page: no change to redirect; any reduction belongs to receipt detail.
- Estimate: current content 3, actions 2; proposed content 3, actions 2; reduction 0%; confidence medium.

### Return Entry And Prerequisite Selection

- Page purpose: scan assets to return to home slot/custody state.
- Primary action: Add to queue.
- Visible items: workflow banner when present, Add to Queue heading, queue helper, scan input, Add to queue, Clear queue, Review Before Return, Queue state, blocked items, recent returned cases verification flash.
- Required: queue state, asset identity, blocked items, home-slot verification after return.
- Nonessential: "Stage scans in the queue, then review the batch before commit" repeats visible controls.
- Simplified page: scan input, queue, Review Before Return. Keep recent return case verification only after commit.
- Estimate: current content 8, actions 6; proposed content 5, actions 5; reduction 29%; confidence high.

### Return Preview

- Page purpose: review queued return assets and commit consequences.
- Primary action: Commit Return.
- Visible items: Back to Return Queue, Ready/Needs Review, explanatory intro, Blocked Items, Assets, Commit intro, responsibility acknowledgment, Commit Return, blocked-state error.
- Required: queued asset identity, destination/home slot, blocked proof, acknowledgment, commit consequence.
- Nonessential: commit intro can be shortened because checkbox already states review.
- Simplified page: review status, assets, blocked items only when present, one commit acknowledgment, Commit Return.
- Estimate: current content 10, actions 3; proposed content 7, actions 2; reduction 31%; confidence high.

### Return Commit Result

- Page purpose: confirm return completion and receipt proof.
- Primary action: review receipt detail or verify case home slots.
- Visible items: returned count, optional verify home slots flash, receipt detail.
- Required: returned count, receipt proof, home slot verification link after return.
- Nonessential: none in redirect.
- Simplified page: no route change; receipt detail/report consolidation covers follow-up.
- Estimate: current content 3, actions 2; proposed content 3, actions 2; reduction 0%; confidence medium.

### Generic Batch Preview

- Page purpose: add staged assets or support legacy Issue-mode review.
- Primary action: Commit staged assets when valid.
- Visible items: Batch Status, Rows, Commit, Issue Mode card, mode toggle, holder summary, Search/select holder, Review issue details.
- Required: batch validity, rows, confirmation checkbox, commit action.
- Risk finding: the Issue Mode section competes with the direct `/issue` workflow and may represent a legacy or partially redundant path. The current recon does not establish whether any active workflow still depends on it.
- Recommendation: do not include removal or relocation of Issue Mode in the presentation implementation phases. Create a separate recon issue to determine whether the path is active, redundant, or safely removable.
- Simplified page model for the currently confirmed batch purpose: batch status, rows, confirmation, and commit. Preserve existing Issue Mode behavior until the separate recon is complete.
- Estimate: current content 11, actions 4; potential future content 6, actions 2; potential reduction 47%; confidence low until path usage is verified.

### Holder Selection

- Page purpose: find and select a custody actor.
- Primary action: Select holder for workflow or inspect holder detail.
- Visible items: Back to workflow, Add Holder, Clear Search, search form, status filter, inactive-holder note, Selected Holder card, directory/results table, Edit, Select, Clear selection.
- Required: selected holder, active/inactive selection boundary, search, select.
- Nonessential: inactive-holder note should show only during assignment selection; it already mostly does. "Current selection" eyebrow duplicates Selected Holder.
- Simplified page: search/filter, selected holder, results. Keep Add Holder but secondary; keep inactive boundary only when `return_to=/issue`.
- Estimate: current content 12, actions 10; proposed content 8, actions 7; reduction 32%; confidence high.

### Holder Detail

- Page purpose: show holder custody state and allow manual follow-up.
- Primary action: inspect assets in custody or send manual follow-up when needed.
- Visible items: back links, holder summary, status, follow-up form, manual-reminder boundary, assets in custody, holder details.
- Required: holder identity, active state, organization, assets in custody, manual-reminder boundary near follow-up action.
- Nonessential: repeated holder detail labels can be shortened; keep follow-up boundary because it prevents mistaking reminder for receipt/custody record.
- Simplified page: holder summary, assets, follow-up collapsed or secondary, details last.
- Estimate: current content 9, actions 5; proposed content 7, actions 4; reduction 21%; confidence medium.

### Add/Edit Holder

- Page purpose: create or update holder reference data for receipt/custody workflows.
- Primary action: Create Holder or Save Holder.
- Visible items: back link, New/Edit Holder heading, helper sentence, organization/email labels, submit button.
- Required: labels, required email indicator, organization selection.
- Nonessential: "A holder can be a person or a group such as a shop, office, or team" can be shortened or linked from only one holder page.
- Simplified page: form only, with one short note on Ad Hoc/group behavior if validation requires it.
- Estimate: current content 3, actions 2 each; proposed content 2, actions 1 each; reduction 40%; confidence high.

### Asset Search

- Page purpose: find asset proof by tag or serial.
- Primary action: Search.
- Visible items: Back to Report, Find Asset, helper text, tag/serial controls, Search, Clear, Assets Found, result-state note, proof links.
- Required: search controls, result count, custody proof/missing proof/conflict status, receipt links.
- Nonessential: helper text can be shortened because labels are clear. Back to Report only when `return_to` exists.
- Simplified page: search controls, results, proof links. Keep missing/conflicting proof visible.
- Estimate: current content 8, actions 5; proposed content 5, actions 4; reduction 31%; confidence high.

### Receipt Detail

- Page purpose: show immutable receipt proof and delivery state.
- Primary action: download PDF or send/resend receipt email when allowed.
- Visible items: Back to Dashboard, Download PDF, Send/Resend, receipt type/status/context, holder follow-up reminder, recovery-mode restriction, What Happened, Do I Need To Act, Who and Where, Receipt Record, Acknowledgment, Issue Location, Assets.
- Required: receipt proof state, receipt type, committed time, holder, location, delivery state, delivery failure truth, recovery-mode restriction, acknowledgment, assets.
- Nonessential: Back to Dashboard duplicates global nav; internal receipt metadata can move below fold or link from report if not needed for action.
- Simplified page: proof header, action row, delivery state, holder/location/assets, failures. Secondary metadata lower.
- Estimate: current content 22, actions 4; proposed content 15, actions 3; reduction 31%; confidence medium.

### Receipt List

- Page purpose: find receipt records.
- Primary action: Search receipts or open receipt detail.
- Visible items: Back links, Search Receipts, three filters, Search, Clear search, Receipt Results, table links and status chips.
- Required: filters, result count, receipt link, delivery status.
- Nonessential: Back to Dashboard duplicates global nav; clear search only when filters active already satisfies condition.
- Simplified page: filters and results only; contextual Back to Report when `return_to=/report`.
- Estimate: current content 5, actions 5; proposed content 4, actions 3; reduction 30%; confidence high.

### Reports

- Page purpose: read-only operational snapshot and drilldowns.
- Primary action: inspect current custody, cases, holders, receipts, or asset search.
- Visible items: Back to Dashboard, report error, Current State, priority copy, Open receipts, include-retired toggle, stat cards, asset/holder/case drilldown links, multiple report sections.
- Required: read-only snapshot, current custody, retired toggle state, drilldown links that preserve `return_to`.
- Nonessential: priority copy and multiple stat-card action labels can be shortened; Back to Dashboard duplicates global nav.
- Simplified page: Current State summary, key drilldowns, tables. Keep report scope and `return_to` links.
- Estimate: current content 18, actions 16; proposed content 11, actions 11; reduction 34%; confidence medium.

### Case And Holder Drilldowns

- Page purpose: inspect case capacity or holders with outstanding assets.
- Primary action: select assets for Issue/Return from case detail, or open holder detail.
- Visible items: contextual Back links, Case Status, Slot Layout, select-all, Start Issue, Assets Issued Out, Start Return, helper notes, holder/case detail links.
- Required: case/slot state, checkbox selection, Start Issue/Return, review-before-commit reminder.
- Nonessential: repeated "Check boxes to select assets" and "Selected assets will be reviewed before commit" can be shortened once per action group.
- Simplified page: case state, selectable sections, Start Issue/Return, one review-before-commit note.
- Estimate: current content 12, actions 9; proposed content 8, actions 7; reduction 29%; confidence medium.

### Admin Tools

- Page purpose: route admins to protected tools and show recovery/system state.
- Primary action: choose admin destination or acknowledge recovery.
- Visible items: Back to Dashboard, recovery mode active panel, grouped tool links, restore history, parse warnings, recovery acknowledgment.
- Required: recovery mode, recovery parse errors, acknowledgment, restore history, protected admin destinations.
- Nonessential: Back to Dashboard duplicates global nav; grouped tool links duplicate admin menu but provide scan-friendly hub.
- Simplified page: keep grouped hub; remove duplicate Back link; collapse restore history details unless recovery mode or recent restore exists.
- Estimate: current content 18, actions 11; proposed content 12, actions 9; reduction 28%; confidence medium.

### Reference Data

- Page purpose: create and correct shared organization/building reference data and mappings.
- Primary action: create reference value or mapping.
- Visible items: Back to Admin Tools, Organizations helper, create org form, Buildings helper, create building form, correction forms, Mapping helper, mapping form.
- Required: headings, forms, correction controls, duplicate/blank validation.
- Nonessential: all three helper paragraphs mostly restate headings and controls.
- Simplified page: forms and tables only, with validation flashes when needed.
- Estimate: current content 7, actions 5 plus row actions; proposed content 4, actions 4 plus row actions; reduction 33%; confidence high.

### User Administration

- Page purpose: create users and manage access.
- Primary action: create user or manage a specific user row.
- Visible items: Back to Admin Tools, temporary password block and warning, disabled-temp warning, Create User, Users, enable/disable, role select, Set Role, Generate Temp Password, disabled helper per row.
- Required: temp password shown once, disabled-account warning, role controls, active state, destructive access changes.
- Nonessential: Back link duplicates admin nav; per-row disabled-temp helper can show only when disabled.
- Simplified page: create user form, compact users table, row actions grouped; keep temp-password warning.
- Estimate: current content 10, actions 12; proposed content 7, actions 9; reduction 27%; confidence medium.

### Holder Import

- Page purpose: upload holder CSV and show import result.
- Primary action: Import Holders.
- Visible items: Back to Admin Tools, Holder CSV Import, file upload, Import Holders, required columns, matching-email behavior, Import Result summary.
- Required: required columns, import result errors, update/create behavior.
- Nonessential: heading plus button already communicate import; matching-email copy can be shortened.
- Simplified page: upload form, required columns line, result summary.
- Estimate: current content 5, actions 2; proposed content 3, actions 1; reduction 43%; confidence high.

### Asset Creation And Asset Edit

- Page purpose: add or update asset metadata and storage relation.
- Primary action: Create Asset or Save Asset.
- Visible items: Back/Admin secondary links, New/Edit Asset helper, location helper, unassigned helper, lookup/select/edit sections, home location relationship note, asset removal notes.
- Required: asset identity fields, home slot relationship boundary, removal/retire boundary.
- Nonessential: "Fill in required fields below" and some helper text repeat labels.
- Simplified page: form sections with only relation/removal boundaries retained.
- Estimate: current content 12, actions 8; proposed content 8, actions 6; reduction 30%; confidence medium.

### Admin Retire, Replace, Slot Move, Force Vacate

- Page purpose: perform destructive or high-risk maintenance.
- Primary action: complete the guarded maintenance action.
- Visible items: lookup/select/current state, warnings, confirmation forms, reason fields, physical verification checkbox, Retire/Replace/Move/Force Vacate buttons.
- Required: terminal/disposed warning, atomic replacement warning, destination-empty requirement, physical verification warning, reason requirement.
- Nonessential: lookup helper text can be shortened; Back links duplicate admin nav.
- Simplified page: keep warnings and confirmations directly beside action; shorten lookup intro.
- Estimate: current content 20, actions 11; proposed content 16, actions 9; reduction 19%; confidence medium.

### Slot Provision And Assign Slot

- Page purpose: add empty slot capacity or assign unslotted assets.
- Primary action: Create empty slots or Assign Slot.
- Visible items: Back/Admin links, assign/create cross-link, create empty slots helper, unslotted list, lookup, selected asset, assign slot form, create empty slots link.
- Required: capacity action, selected asset state, building/case/slot choices, assignment validation.
- Nonessential: cross-links appear both in nav and below form; helper can shorten.
- Simplified page: one cross-link, one selected asset state, assignment form.
- Estimate: current content 10, actions 8; proposed content 7, actions 6; reduction 28%; confidence medium.

### Receipt CC Settings

- Page purpose: configure local receipt CC delivery metadata.
- Primary action: Save CC.
- Visible items: Back, current CC state, source/fallback status, Change or clear helper, Save CC, clearing fallback note.
- Required: current active CC, source/fallback, delivery-metadata boundary.
- Nonessential: clearing fallback note can show only when fallback exists or after clear.
- Simplified page: current state, editor, save. Conditional fallback note.
- Estimate: current content 7, actions 2; proposed content 5, actions 1; reduction 33%; confidence medium.

### Admin Report And Backup

- Page purpose: admin read-only operational report and backup access.
- Primary action: read report, download PDF, download DB backup.
- Visible items: Back to Admin Tools, Download PDF, Download Database Backup, Report Scope, read-only caveat, DB path, recent events, report sections.
- Required: read-only report boundary, backup action, DB path for admin ops.
- Nonessential: "This surface does not replace a database backup" can be replaced by existing Download Database Backup action when present.
- Simplified page: Report Scope with DB path, report tables, action row.
- Estimate: current content 8, actions 3; proposed content 6, actions 2; reduction 27%; confidence medium.

### Restore And Recovery

- Page purpose: validate backup, confirm live replacement, preserve rollback, activate recovery mode, guide acknowledgment.
- Primary action: Validate Backup, then Replace Live Database after explicit confirmation.
- Visible items: Back, errors/success, Restore SQLite Backup warning, Validate Backup, Validation Summary, Confirm Live Replacement warning, admin password, Replace Live Database, Clear Validation, Operational Paths, After Restore sequence, Restore Result.
- Required: validation-before-replacement, admin password, rollback, recovery activation, restore history, no custody events, no rebuild after backup, post-restore sequence.
- Nonessential: Operational Paths can be lower or collapsed, but not removed. Back link duplicates admin nav.
- Simplified page: keep all destructive/recovery warnings; move operational paths after confirm/result.
- Estimate: current content 18, actions 5; proposed content 15, actions 4; reduction 17%; confidence high.

## 10. Remove Candidates

| Surface | Item | Current purpose | Why protected after removal |
|---|---|---|---|
| Dashboard | Second custody-map explanatory sentence | Warns map is orientation only | One read-only custody-map note remains visible |
| Reference Data | "Create reference values before using them..." | Explains org creation | Heading and form labels already carry the task; validation remains |
| Reference Data | "Building values appear..." | Explains building creation | Issue/admin selectors already use buildings; no action risk |
| Reference Data | "Map organizations..." | Explains mapping | Mapping heading and select labels state same action |
| Holder forms | Generic holder-can-be-person/group sentence | Orients holder creation | Required validation and labels remain; detailed guidance can live in holder docs |
| Generic Preview | Issue Mode details on generic preview | Legacy route support | Direct `/issue` and `/issue/preview` are authoritative workflow surfaces |

## 11. Consolidation Candidates

| Surface | Item | Category | Recommended consolidation |
|---|---|---|---|
| Global/local nav | Back to Dashboard repeated | Consolidate | Keep global Dashboard, use local back only for `return_to` |
| Admin pages | Back to Admin Tools repeated | Consolidate | Keep Admin menu and Admin Tools hub; local back only for multi-step admin flows |
| Issue/Return queue | Repeated queue/review helper copy | Consolidate | One workflow standard for queue before preview |
| Case detail | Repeated checkbox/review notes | Consolidate | One note per Issue/Return action group |
| Receipt proof/report links | Multiple proof entry points | Consolidate | Report links to receipts and asset search remain authoritative |

## 12. Replace-With-Existing-Link Candidates

| Surface | Item | Existing destination | Conditions |
|---|---|---|---|
| Receipt detail | Secondary receipt list exploration | `/receipts` | Safe when operator does not need search to complete current receipt action |
| Report | Receipt supporting detail | `/receipts?return_to=/report` | Existing `return_to` preserves report path |
| Report | Asset proof drilldown | `/assets/search?return_to=/report` | Existing return link preserves report context |
| Case/holder drilldowns | Holder proof detail | `/holders/<id>?return_to=/report` | Existing return link preserves report context |
| Admin report | Backup caveat | `/admin/db/export` action | Only as action label; backup remains available |

Not recommended as link-only yet:

- Holder/location custody model copy on Issue Preview. An operator model document exists under docs, but there is no current in-app route that safely presents it without creating a workflow dead end.

## 13. Show-Only-When-Relevant Candidates

| Surface | Item | Triggering condition |
|---|---|---|
| Issue current location | Organization building limit note | Selected holder has mapped organization buildings |
| Holder selection | Inactive holders hidden note | `return_to` targets Issue or other active-only assignment flow |
| Receipt CC | Environment fallback note | Fallback exists or local setting was cleared |
| User admin | Disabled temp-password warning | User is disabled and temp password was generated or row is disabled |
| Recovery banner | Recovery Mode Active | Recovery mode state is active |
| Restore history parse warning | Parse error | Restore history cannot be read cleanly |
| Blocked Items | Blocked item section | Blocking issues exist |
| Receipt resend blocked | Recovery restriction | Recovery mode active |
| Recent return case verification | Verify home slots flash | Return commit just succeeded |

## 14. Shortening Candidates

| Surface | Current fact to preserve | Shortening target |
|---|---|---|
| Issue queue | Holder and current location must be set before scan | "Set holder and location before scanning." |
| Return queue | Queue must be reviewed before commit | "Review queued returns before commit." |
| Asset search | Asset tag wins over serial when both entered | "Asset tag is used first." |
| Holder import | Required columns and email matching behavior | "Required: organization, name, email. Matching email updates." |
| Admin new asset | Asset type default | "Default type: Laptop." |
| Restore | Validate before live replacement | Keep fact, reduce surrounding prose only |
| Admin report | Read-only report, not backup | "Read-only. Use Download Database Backup for backup." |

## 15. Standardization Candidates

| Surface | Item | Standard |
|---|---|---|
| Issue/Return queue | Review button labels | "Review Before Issue" / "Review Before Return" |
| Issue/Return preview | Commit intro | One sentence, same structure |
| Back links | Local navigation labels | Use "Back to [workflow/report]" only when preserving context |
| Queue empty state | Empty queue copy | "No assets queued." |
| Blocked state | Blocked Items heading | Same heading and placement across Issue/Return |
| Admin destructive warnings | Warning placement | Directly above destructive submit button |

## 16. Keep-Visible Content

| Protected item | Where it must remain visible | Risk prevented |
|---|---|---|
| Custody actor | Issue banner, holder selection, Issue preview, receipt detail | Issuing to wrong holder |
| Receiving/destination holder | Issue queue and Issue preview | Wrong custody transfer |
| Current location | Issue entry, Issue preview, receipt detail | Incorrect location context |
| Asset identity | Queue, preview, receipt, report, asset search | Wrong asset transfer |
| Queue state | Issue/Return queue and preview | Committing unseen assets |
| Preview contents | Issue/Return preview | Appending events without review |
| Commit target | Commit cards and buttons | Wrong workflow commit |
| Commit consequences | Commit acknowledgment text | Irreversible custody/event append misunderstanding |
| Receipt proof state | Receipt detail and receipt list | Confusing proof with delivery |
| Receipt delivery failure truth | Receipt detail send/resend errors | Belief that custody/receipt rolled back |
| Missing custody proof | Asset search/report proof surfaces | Hidden integrity gap |
| Conflicting custody state | Validation/blocking sections | Unsafe commit |
| Recovery-mode warnings | Global recovery banner, receipt resend, admin tools | Unsafe resend/retry during recovery |
| Permission denial | 403 page and protected route flashes | Role-boundary confusion |
| Destructive-action warnings | Retire, replace, restore, force vacate | Irreversible or high-risk admin action |

## 17. Do-Not-Change Content

Do not change these without separate issue scope:

- Recovery restore warning and confirmation language.
- Force-vacate physical verification warning.
- Retire terminal/disposed warning.
- Replacement atomic-operation warning.
- Receipt delivery failure truth stating custody and receipt records remain intact.
- Permission denial copy.
- Password temporary one-time visibility warning.
- Issue/Return responsibility acknowledgment checkboxes.
- Blocked item and validation messages.
- Missing or conflicting proof indicators.

These protect custody truth, safety, recovery, security, destructive actions, or irreversible consequences.

## 18. Navigation And Dead-End Risks

Risks found:

- Removing local Back links blindly can strand report drilldowns. Keep `return_to` links where they preserve report or workflow intent.
- Replacing Issue Preview guidance with a repository-document link is unsafe. Shorten or standardize the guidance instead. Any future in-app help destination requires separate approval and must preserve queue/session state and return cleanly.
- Generic `/preview` still contains Issue Mode and issue-detail links. Treat this as a separate recon item because removal could affect legacy Add Assets or Issue-mode paths and may exceed Class 1 presentation scope.
- Admin Tools duplicates global admin menu, but removing the hub would make admin discovery harder under pressure.
- Report, receipt, asset search, holder detail, and case detail form a useful proof graph. Consolidate labels, not route access.

## 19. Workflow Seam Risks

The workflow seam must remain:

entry page -> prerequisite selection -> scan queue -> preview -> commit

Do not recommend:

- entry redirecting to preview
- preview bypassing queue
- scan before required holder/current location
- commit without preview confirmation
- hiding blocked items
- hiding queue count
- hiding selected holder or current location
- changing `return_to`
- changing route behavior

Safe simplification is presentation-only inside existing pages.

## 20. Application-Wide Reduction Estimate

Weighted estimate, using content items plus action/navigation items:

| Area | Current load | Proposed load | Reduction | Confidence |
|---|---:|---:|---:|---|
| Shared shell/navigation | 32 | 22 | 31% | Medium |
| Operator workflows | 96 | 65 | 32% | High |
| Operator proof/report surfaces | 106 | 69 | 35% | Medium |
| Admin hub/reference/user/import | 59 | 39 | 34% | Medium |
| Admin maintenance/recovery/destructive | 64 | 52 | 19% | Medium |
| Total reviewed | 357 | 247 | 31% | Medium |

Planning interpretation:

- The safe full-application reduction is about 31% using all protected content and actions in the denominator.
- If limited to nonessential presentation load, the removable share is about 55% to 60%.
- The 50% target is realistic only for the nonessential subset.

## 21. Recommended Phased Implementation Issues

### Issue 27-XXX: Reduce Shared And Page-Level Navigation Duplication

- Change classification: Class 1 - UI / Presentation.
- Purpose: remove duplicate local navigation while preserving `return_to`.
- Exact surfaces: `base.html`, page-level local nav blocks on report/admin/operator pages.
- Exact reduction target: remove 10 to 14 duplicate action links.
- Scope: local Back links that duplicate global nav; keep workflow/report `return_to`.
- Non-goals: no route, redirect, auth, form, or workflow changes.
- Protected information: recovery banner, permission denial, workflow context.
- Risks: dead ends if `return_to` links are removed.
- Automated verification: existing nav/auth tests plus targeted template assertions.
- Manual smoke test: Dashboard -> Report -> Asset Search -> back; Admin Tools -> child page -> back/global nav.
- Expected files: templates only.
- Recommended order: 1.

### Issue 27-XXX: Simplify Dashboard And Workflow Entry Copy

- Change classification: Class 1 - UI / Presentation.
- Purpose: reduce dashboard/entry reading burden.
- Exact surfaces: `dashboard.html`, Issue/Return entry portions of `return_queue.html`.
- Exact reduction target: remove or shorten 8 to 12 content items.
- Scope: helper paragraphs and duplicate action labels.
- Non-goals: no dashboard query, custody, queue, or workflow changes.
- Protected information: custody map read-only boundary, Issue/Return entry actions, holder/current-location prerequisites.
- Risks: weakening prerequisite clarity.
- Automated verification: dashboard tests, Issue location tests, Return queue tests.
- Manual smoke test: dashboard to Issue, dashboard to Return, direct `/issue`, direct `/return`.
- Expected files: templates and focused tests only.
- Recommended order: 2.

### Issue 27-XXX: Reduce Issue Workflow Presentation Load

- Change classification: Class 1 - UI / Presentation.
- Purpose: keep Issue seam clear while removing repeated guidance.
- Exact surfaces: Issue rendering in `return_queue.html`, `issue_preview.html`, `_workflow_context_banner.html`.
- Exact reduction target: remove or shorten 10 to 15 content/action items.
- Scope: helper copy, secondary action emphasis, duplicate holder/location explanation.
- Non-goals: no workflow, queue, preview, commit, event, receipt, or holder logic changes.
- Protected information: custody actor, current location, queue state, preview contents, commit target, acknowledgment.
- Risks: hiding required prerequisite state.
- Automated verification: `tests/test_issue_location_wiring.py`, `tests/test_issue_23_2_preview_commit_seam.py`, `tests/test_issue_holder_prerequisite.py`.
- Manual smoke test: select holder, set location, scan, preview, commit with safe data.
- Expected files: Issue templates and focused tests only.
- Recommended order: 3.

### Issue 27-XXX: Reduce Return Workflow Presentation Load

- Change classification: Class 1 - UI / Presentation.
- Purpose: shorten Return queue and preview guidance while protecting home-slot proof.
- Exact surfaces: Return rendering in `return_queue.html`, `return_preview.html`.
- Exact reduction target: remove or shorten 6 to 10 content/action items.
- Scope: queue helper copy, commit intro, blocked-state placement.
- Non-goals: no return validation, queue, preview, commit, event, or receipt changes.
- Protected information: asset identity, home slot, blocked items, acknowledgment, receipt creation.
- Risks: hiding home-slot verification.
- Automated verification: `tests/test_return_batch.py`, queue/preview tests.
- Manual smoke test: scan return asset, preview, commit with safe data, verify case link flash.
- Expected files: Return templates and focused tests only.
- Recommended order: 4.

### Issue 27-XXX: Simplify Holder And Asset Search Surfaces

- Change classification: Class 1 - UI / Presentation.
- Purpose: reduce search/filter/helper load while preserving custody actor and proof discovery.
- Exact surfaces: `holders_search.html`, `holder_detail.html`, `holder_new.html`, `holder_edit.html`, `asset_search.html`.
- Exact reduction target: remove or shorten 10 to 14 content/action items.
- Scope: helper text, secondary actions, repeated selected-holder labels.
- Non-goals: no holder creation/edit behavior, search query behavior, follow-up email behavior, or proof logic changes.
- Protected information: active holder boundary, selected holder, manual reminder boundary, missing/conflicting proof.
- Risks: weakening holder-as-custody-actor clarity.
- Automated verification: holder tests, asset search UI tests.
- Manual smoke test: search holder, select holder for Issue, view holder detail, asset search proof.
- Expected files: holder/search templates and focused tests only.
- Recommended order: 5.

### Issue 27-XXX: Consolidate Receipt, Proof, And Report Links

- Change classification: Class 1 - UI / Presentation.
- Purpose: keep proof visible while reducing repeated report/receipt navigation and secondary metadata.
- Exact surfaces: `receipt_detail.html`, `receipts_list.html`, `report_readonly.html`, dashboard drilldown templates.
- Exact reduction target: remove or shorten 12 to 18 content/action items.
- Scope: duplicate Back links, supporting metadata placement, stat action labels.
- Non-goals: no receipt generation, delivery, resend, report query, or proof logic changes.
- Protected information: receipt proof state, delivery failure truth, missing proof, conflicting custody proof.
- Risks: hiding proof or delivery failure state.
- Automated verification: receipt detail/list tests, report tests, asset search proof tests.
- Manual smoke test: open report, asset proof, receipt detail, failed receipt state if available.
- Expected files: receipt/report templates and focused tests only.
- Recommended order: 6.

### Issue 27-XXX: Reduce Admin Hub And Admin Description Load

- Change classification: Class 1 - UI / Presentation.
- Purpose: remove helper copy that restates admin controls.
- Exact surfaces: `admin_system.html`, `admin_reference_data.html`, `admin_holder_import.html`, `admin_human_report.html`, `admin_receipt_cc.html`.
- Exact reduction target: remove or shorten 10 to 15 content/action items.
- Scope: helper paragraphs, duplicate hub links, conditional fallback notes.
- Non-goals: no role, reference-data, import, backup, report, or receipt-CC behavior changes.
- Protected information: admin-only boundary, receipt CC metadata boundary, backup/report distinction.
- Risks: hiding admin destination discoverability.
- Automated verification: admin reference data, admin system health, receipt CC tests.
- Manual smoke test: admin menu, reference data, holder import, report backup link, receipt CC.
- Expected files: admin templates and focused tests only.
- Recommended order: 7.

### Issue 27-XXX: Normalize Workflow Conditional Guidance

- Change classification: Class 1 - UI / Presentation.
- Purpose: show workflow guidance and blocked-state content only when the triggering workflow state exists.
- Exact surfaces: holder selection, Issue current-location guidance, Issue blocked sections, Return blocked sections, recent-return verification guidance.
- Exact reduction target: remove or conditionally hide 3 to 6 warning/status items when inactive.
- Scope: conditional presentation only where the required state already exists.
- Non-goals: no holder-selection, location-validation, queue, preview, commit, event, receipt, or route behavior changes.
- Protected information: active-holder boundary, missing prerequisites, blocked items, queue state, post-return home-slot verification.
- Risks: hiding a prerequisite or blocked-state explanation before the operator can act safely.
- Automated verification: holder-selection tests, Issue location/prerequisite tests, Issue and Return blocked-state tests.
- Manual smoke test: Issue with and without mapped organization limits, inactive-holder selection, blocked Issue asset, blocked Return asset, successful Return with case verification.
- Expected files: workflow templates and focused tests only.
- Recommended order: 8.

### Issue 27-XXX: Normalize Admin, Recovery, And Receipt Conditional Guidance

- Change classification: Class 1 - UI / Presentation.
- Purpose: show secondary admin, recovery, and receipt-delivery guidance only under the state that requires it while preserving all permanent high-risk warnings.
- Exact surfaces: recovery banner, Admin Tools recovery history, restore parse warnings, receipt detail delivery failure/recovery restriction, receipt CC fallback state, user administration disabled/temp-password guidance.
- Exact reduction target: remove or conditionally hide 3 to 6 status items when inactive.
- Scope: conditional presentation only where existing state already controls visibility.
- Non-goals: no recovery, restore, receipt delivery, resend, receipt CC, authentication, role, password, or permission behavior changes.
- Protected information: recovery mode, restore validation/replacement warnings, receipt delivery failure truth, resend restrictions, permission denial, one-time temporary-password warning.
- Risks: hiding a recovery restriction, receipt failure truth, or account-security warning.
- Automated verification: recovery, restore, receipt detail/resend, receipt CC, and user-administration tests.
- Manual smoke test: recovery inactive/active, restore validation error/success, receipt pending/sent/failed, resend blocked during recovery, fallback CC present/absent, enabled/disabled user states.
- Expected files: admin/receipt/shared templates and focused tests only.
- Recommended order: 9.

### Separate Recon Required: Determine The Future Of Generic `/preview` Issue Mode

- Change classification: Planning / Recon.
- Purpose: determine whether generic `/preview` Issue Mode is active, redundant, legacy, or safely removable.
- Exact surfaces: generic `preview.html`, related route handlers, tests, links, and any Add Assets or Issue-mode entry paths.
- Scope: trace route usage, entry points, session/queue assumptions, and operator dependencies.
- Non-goals: no removal, redirect, route change, template change, or workflow change during recon.
- Protected information: queue state, holder selection, preview confirmation, direct `/issue` entry behavior, safe `return_to`.
- Risks: removing a still-active workflow seam or creating a dead-end state.
- Verification expectation: documentation-only artifact plus route/test evidence.
- Recommended timing: after the first navigation/dashboard simplification issues and before any attempt to remove Issue Mode from generic preview.

## 22. Recommended Implementation Order

1. Shared and page-level navigation reduction.
2. Dashboard and workflow-entry simplification.
3. Issue workflow presentation reduction.
4. Return workflow presentation reduction.
5. Holder and asset-search simplification.
6. Receipt, proof, and report-link consolidation.
7. Admin Tools and admin-description reduction.
8. Workflow conditional-guidance normalization.
9. Admin, recovery, and receipt conditional-guidance normalization.

Do not combine Issue and Return workflow reductions in one issue. Each workflow seam needs independent review and smoke testing.

Do not include generic `/preview` Issue Mode removal in these implementation phases. Create a separate recon issue first to determine whether that path is active, redundant, or safely removable.

## 23. Explicit Non-Changes Confirmation

This recon recommends no implementation in this issue.

Do not change:

- code
- templates
- tests
- routes
- redirects
- `return_to` behavior
- workflow order
- forms
- queue behavior
- preview behavior
- commit behavior
- custody behavior
- event behavior
- receipt behavior
- permissions
- role enforcement
- schema
- migrations
- persistence
- dependencies
- brand design
- design system

Any future implementation issue must stay presentation-only unless separately approved.
