# Issue 27-148 Recon: Menu Order And Navigation Simplicity

## Answer

Recommended path: keep the primary operator nav short and action-first:

```text
Dashboard -> Issue -> Return -> Holders -> Reports
```

Keep admin/support work behind the Admin menu and Admin Tools page. Do not re-add
Manual Add Assets to normal navigation.

Why it matters: operators under time pressure should see the next custody action
without sorting through maintenance, support, or historical batch-creation tools.

## Sutherland Lens

- headings should carry meaning before helper text is added
- reduce clutter before adding explanatory copy
- Issue and Return must stay obvious
- admin-only maintenance should not compete with normal operator actions
- page-specific wording cleanup belongs in follow-on issues, not this nav census

## Current Navigation/Menu Map

Primary top nav in `base.html`:

| Surface | Visible to | Current label | Destination | Notes |
| --- | --- | --- | --- | --- |
| Top nav | signed-in users | Dashboard | `/dashboard` | Read-only orientation and action cards. |
| Top nav | signed-in users | Issue | `/issue` | Must remain prominent. Renders workflow page directly. |
| Top nav | signed-in users | Return | `/return` | Must remain prominent. Renders workflow page directly. |
| Top nav | signed-in users | Holders | `/holders` | Holder search, selection, detail, and holder actions. |
| Top nav | signed-in users | Reports | `/report` | Also marks receipts, asset search, holder/case drilldowns active. |
| Top nav details | admins | Admin | admin destinations | Separates maintenance from operator actions. |
| Utility nav | signed-in users | Account | `/account/change-password` | Account maintenance. |
| Utility nav | signed-in users | Logout | `/logout` | Session exit. |
| Utility badge | admins | ADMIN | no route | Mode indicator only. |
| Recovery banner | admins during recovery | Review Recovery State | `/admin/system` | Correctly interruptive because recovery blocks receipt delivery actions. |

Current Admin menu destinations:

| Current label | Destination | Category |
| --- | --- | --- |
| Users | `/admin/users` | access control |
| Admin Tools | `/admin/system` | admin hub |
| Reference Data | `/admin/reference-data` | setup data |
| Import Holders | `/admin/holders/import` | import/support |
| Operational Report | `/admin/report` | admin report |
| Restore Database | `/admin/db/restore` | recovery/support |

## Visible Operator Action Map

Dashboard action surfaces:

| Surface | Current action | Destination | Operator meaning |
| --- | --- | --- | --- |
| Assets Out card | View Current Custody | `/report` | see what is out |
| Assets Remaining card | Review case space | `/dashboard/cases` | inspect storage/case capacity |
| Total Assets card | Search assets | `/assets/search` | find an asset |
| Issue Assets card | Open Issue Workflow | `/issue` | start issuing |
| Return Assets card | Open Return Workflow | `/return` | start returning |
| Custody Map | expandable map | same page/drilldowns | orientation only |

Workflow entry and local workflow nav:

| Surface | Current action | Destination | Constraint |
| --- | --- | --- | --- |
| `/issue` | queue scans, update location, review | `/issue/preview` after queue | entry route renders the Issue page directly |
| `/return` | queue scans, review | `/return/preview` after queue | entry route renders the Return page directly |
| Case detail | Start Issue | `/dashboard/cases/<case>/queue` then `/issue` | queues selected assets before workflow entry |
| Case detail | Start Return | `/dashboard/cases/<case>/queue` then `/return` | queues selected assets before workflow entry |
| Issue preview | Back to Batch Preview | `/preview` | legacy/generic preview path remains reachable |
| Issue preview | Change holder / Select holder | `/holders?return_to=/issue` | supports prerequisite selection |
| Return preview | commit return | `/return/commit` | preview remains distinct from commit |
| Holder search/detail | Select for Issue / Select Holder | holder selection POST | supports Issue prerequisite |

Report/support surfaces visible to operators:

| Surface | Current action | Destination |
| --- | --- | --- |
| Current System State | Open receipts | `/receipts` |
| Current System State | Include retired assets / active only | `/report?...` |
| Report tables | asset/holder/case drilldowns | `/assets/search`, `/holders/<id>`, `/dashboard/cases/<case>` |
| Receipts list | Search Receipts | `/receipts` query |
| Receipt detail | Download Receipt PDF | `/receipts/<id>/pdf` |
| Receipt detail | Send Receipt Email | `/receipts/<id>/send` |

## Admin/Support Action Map

Admin Tools page:

| Current label | Destination | Recommended category |
| --- | --- | --- |
| Create empty slots | `/admin/slots/provision` | storage setup |
| Assign unslotted asset | `/admin/assign-slot` | storage setup |
| Manage Users | `/admin/users` | access control |
| Manage Organizations and Buildings | `/admin/reference-data` | reference setup |
| Receipt CC Settings | `/admin/receipt-cc` | delivery settings |
| Import Holders from CSV | `/admin/holders/import` | import/support |
| Open Operational Report | `/admin/report` | admin report |
| Restore Database Backup | `/admin/db/restore` | recovery/support |
| Download Database Backup | `/admin/db/export` | backup/support |

Admin-only or admin-sensitive local actions outside the Admin Tools grid:

| Surface | Action | Destination |
| --- | --- | --- |
| Receipt detail | Resend receipt email | `/receipts/<id>/resend` |
| Admin report | Download PDF | `/admin/report/pdf` |
| Admin report | Download Database Backup | `/admin/db/export` |
| Holder detail | Deactivate/Reactivate Holder | `/holders/<id>/toggle-active` |
| Recovery banner/Admin Tools | Acknowledge Recovery and Resume | `/admin/recovery/acknowledge` |

## Hidden Or Direct-Only Route Map

These routes exist but should not become normal top-level navigation without a
separate issue:

| Route | Current role | Recommendation |
| --- | --- | --- |
| `/add-assets` | manual batch creation page | keep direct URL only |
| `/add-assets/review` | manual Add Assets review POST | keep hidden behind direct flow |
| `/preview` | generic legacy preview | keep out of top nav |
| `/preview/validate` | validation endpoint | keep hidden |
| `/preview/mode` | legacy Issue mode POST | keep hidden |
| `/preview/discard` | batch discard POST | keep hidden/local only |
| `/preview/commit` | generic commit POST | keep hidden/local only |
| `/lock` | intake lock route | keep local/direct |
| `/bootstrap/admin` | first-admin bootstrap | keep hidden after setup |
| `/demo` and `/demo/send-sample-receipt` | isolated demo | keep separate from app nav |
| `/admin/assets/new` | admin asset creation | keep out of normal operator nav |
| `/admin/assets/edit` | admin asset maintenance | keep admin-only/direct or Admin Tools follow-on |
| `/admin/assets/retire` | admin asset retirement | keep admin-only/direct or Admin Tools follow-on |
| `/admin/assets/replace` | admin replacement workflow | keep admin-only/direct or Admin Tools follow-on |
| `/admin/assets/create` | admin create API | keep hidden |
| `/admin/events/correct` | event correction API | keep hidden |
| `/admin/slot-move` | slot maintenance | keep admin-only/direct or Admin Tools follow-on |
| `/admin/force-vacate` | slot maintenance | keep admin-only/direct or Admin Tools follow-on |
| `/receipts/<id>/resend` GET | redirect guard | keep hidden |

Known constraints:

- Manual Add Assets launchers are hidden from normal navigation.
- `/add-assets` remains available by direct URL.
- Import/upload paths remain intact.
- Workflow entry routes must render their workflow page directly.
- `/issue` and `/return` must not redirect directly to preview.
- Preview assumes a populated queue.

## Recommended Operator-First Menu Order

Recommended primary top nav:

```text
Dashboard -> Issue -> Return -> Holders -> Reports
```

Rationale:

- Dashboard first gives calm state and orientation.
- Issue and Return stay immediately available because they are the core custody actions.
- Holders remains visible because holder selection and holder detail are operational, not merely admin.
- Reports stays after active workflow and holder actions because it is read-only lookup.
- Do not add Manual Add Assets, Receipts, Search, or Cases as top-level items yet; they are reachable through Dashboard/Reports and adding them would increase choice load.

Small label consideration for follow-up only:

- `Reports` currently includes report, receipts, asset search, holder drilldowns, and case drilldowns. If operators misunderstand it, consider a focused label issue such as `Status` or `Lookup`, but do not bundle that with route changes.

## Recommended Admin/Support Menu Order

Recommended Admin menu:

```text
Admin Tools -> Users -> Reference Data -> Import Holders -> Operational Report -> Restore Database
```

Rationale:

- Admin Tools first gives one hub before specific maintenance choices.
- Users and Reference Data are setup/admin fundamentals.
- Import Holders is support/setup, not a normal operator action.
- Operational Report is admin read-only support.
- Restore Database should stay last because it is high-risk recovery.

Recommended Admin Tools grouping for a follow-on issue:

```text
Access
- Manage Users

Setup Data
- Manage Organizations and Buildings
- Import Holders from CSV

Storage
- Create empty slots
- Assign unslotted asset

Delivery
- Receipt CC Settings

Reports And Backup
- Open Operational Report
- Download Database Backup
- Restore Database Backup
```

This should be a small presentation-only follow-on if implemented. Do not mix it
with route changes or workflow behavior.

## Items That Should Stay Hidden From Normal Navigation

- Manual Add Assets launchers.
- Generic `/preview` and preview POST endpoints.
- Bootstrap/admin setup route.
- Demo routes.
- Admin create/edit/retire/replace asset maintenance routes unless a dedicated Admin Tools grouping issue exposes them intentionally.
- Event correction API.
- Slot move and force-vacate routes unless a dedicated admin maintenance issue exposes them intentionally.
- Receipt resend GET redirect guard.

Why it matters: these are either legacy, direct-only, admin-only, recovery, or
dangerous maintenance surfaces. Normal navigation should keep operators focused
on Dashboard, Issue, Return, Holders, and Reports.

## Risks If Changed Directly Without Follow-On Issues

- Moving Issue or Return deeper can delay the next custody action under field pressure.
- Redirecting `/issue` or `/return` to preview would break the required seam because preview assumes a populated queue.
- Adding hidden/direct routes to top nav can mix admin maintenance with operator work.
- Re-adding Manual Add Assets can reverse the recent decision to hide manual launchers while keeping direct URL access.
- Moving report/search/receipt links into primary nav may create clutter instead of clarity.
- Renaming `Reports` without operator validation may hide asset search, receipts, or case/holder drilldowns.
- Changing admin menu order without tests/manual smoke can accidentally hide recovery, user, or import tools from admins.
- Navigation changes affecting workflows require manual operator smoke tests.
- Do not add more explanatory page copy when a clearer heading would solve the problem.

## Small Follow-On Issue Recommendations

1. **Issue 27-148A: Reorder primary top nav only if operator testing says current order is slow**
   - Scope: `base.html` top nav order only.
   - Candidate order: `Dashboard -> Issue -> Return -> Holders -> Reports`.
   - Verification: login as operator/admin, open each top nav item, smoke Issue and Return entry pages.

2. **Issue 27-148B: Put Admin Tools first inside the Admin menu**
   - Scope: Admin details menu order only.
   - Verification: admin login, open each admin menu destination.

3. **Issue 27-148C: Group Admin Tools page links by operational category**
   - Scope: `admin_system.html` presentation only.
   - Candidate groups: Access, Setup Data, Storage, Delivery, Reports And Backup.
   - Keep admin-only maintenance separate from operator actions.

4. **Issue 27-148D: Decide whether `Reports` should be renamed**
   - Scope: label/recon only first.
   - Question: does `Reports` clearly cover current state, receipts, search, cases, and holder drilldowns?
   - Do not implement without operator validation.

5. **Issue 27-148E: Review holder search local nav**
   - Scope: page-specific cleanup.
   - Reason: holder search still shows `Back to preview | Issue Assets`, which may reflect older preview-centered flow.
   - Preserve holder selection return paths.

6. **Issue 27-148F: Review legacy generic preview visibility**
   - Scope: recon first.
   - Reason: `/preview` and Issue-mode links still exist for the direct Add Assets/generic batch path.
   - Preserve `/issue` and `/return` entry behavior.

7. **Issue 27-148G: Review admin asset maintenance exposure**
   - Scope: admin-only navigation decision.
   - Question: should create/edit/retire/replace/slot move/force-vacate remain direct-only or appear in a grouped maintenance section?
   - Do not mix with workflow nav cleanup.

## Verification Notes

Inspected:

- `assettrack/intake/templates/base.html`
- `assettrack/intake/templates/dashboard.html`
- `assettrack/intake/templates/admin_system.html`
- `assettrack/intake/templates/report_readonly.html`
- `assettrack/intake/templates/receipts_list.html`
- `assettrack/intake/templates/receipt_detail.html`
- `assettrack/intake/templates/holders_search.html`
- `assettrack/intake/templates/holder_detail.html`
- `assettrack/intake/templates/issue_preview.html`
- `assettrack/intake/templates/return_queue.html`
- `assettrack/intake/templates/return_preview.html`
- `assettrack/intake/app.py` route definitions

No implementation was performed.
