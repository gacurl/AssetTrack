# Issue 27-156 Recon: App Bloat And Navbar Friendliness

## Answer

AssetTrack does not need more top-level navigation before deployment. It needs
less visible competition around the core custody path.

Recommended operator streamline order:

```text
Dashboard -> Issue -> Return -> Holders -> Reports
```

Recommended admin/support posture:

```text
Admin -> Admin Tools hub -> grouped admin/support sections
```

Why it matters: field operators should find Issue, Return, Holders, and Reports
without sorting through support tools, diagnostics, recovery details, or legacy
batch-creation paths.

## 1. Current Visible Operator Nav

Primary navbar in `base.html`:

| Label | Route | Friendliness finding |
| --- | --- | --- |
| Dashboard | `/dashboard` | Good first stop for state and next action. |
| Issue | `/issue` | Good. Must remain prominent. |
| Return | `/return` | Good. Must remain prominent. |
| Holders | `/holders` | Good. Operationally important for Issue selection and holder lookup. |
| Reports | `/report` | Useful but broad. It also covers receipts, asset search, case drilldowns, and holder drilldowns. |
| Account | `/account/change-password` | Utility link. Fine outside primary action group. |
| Logout | `/logout` | Utility link. Fine outside primary action group. |

Dashboard visible action cards:

| Card/action | Destination | Finding |
| --- | --- | --- |
| View Current Custody | `/report` | Useful, but duplicates top nav Reports. |
| Review case space | `/dashboard/cases` | Useful for storage/case work, but "case space" is less direct than Issue/Return. |
| Search assets | `/assets/search` | Useful lookup, currently nested under Dashboard/Reports behavior. |
| Open Issue Workflow | `/issue` | Good duplicate of top nav because it is a primary next action. |
| Open Return Workflow | `/return` | Good duplicate of top nav because it is a primary next action. |
| Custody Map disclosure | Dashboard only | Useful orientation, but visually large and not a launch action. |

Operator nav is mostly friendly because Issue and Return are visible. The bloat
pressure is below the navbar: dashboard cards, report utilities, local back
links, and legacy/direct-only workflow surfaces.

## 2. Current Visible Admin Nav

Admin dropdown in `base.html`:

| Label | Route | Finding |
| --- | --- | --- |
| Users | `/admin/users` | Access control. Important, but not the admin hub. |
| Admin Tools | `/admin/system` | Hub. Should probably appear first in the dropdown. |
| Reference Data | `/admin/reference-data` | Setup/support. |
| Import Holders | `/admin/holders/import` | Import/support. |
| Operational Report | `/admin/report` | Admin report. |
| Restore Database | `/admin/db/restore` | Recovery. High-risk; should stay separated and late. |

Admin Tools page:

| Label | Route | Finding |
| --- | --- | --- |
| Create empty slots | `/admin/slots/provision` | Storage setup. |
| Assign unslotted asset | `/admin/assign-slot` | Storage setup. |
| Manage Users | `/admin/users` | Access control. |
| Manage Organizations and Buildings | `/admin/reference-data` | Setup data. Long label but clear. |
| Receipt CC Settings | `/admin/receipt-cc` | Delivery settings. |
| Import Holders from CSV | `/admin/holders/import` | Import/support. |
| Open Operational Report | `/admin/report` | Admin report. |
| Restore Database Backup | `/admin/db/restore` | Recovery. |
| Download Database Backup | `/admin/db/export` | Backup/support secondary action. |

Admin Tools also includes system snapshot, recovery state, restore history, and
recovery acknowledgment. That is valuable admin context, but it mixes launch
actions, diagnostics, backup, restore, recovery, and metadata on one page.

## 3. Current Local Page Nav Patterns

Common patterns found:

| Surface | Pattern | Finding |
| --- | --- | --- |
| Workflow previews | `Back to ... Queue` or `Back to Batch Preview` | Useful, but Issue preview still points to generic Batch Preview. |
| Holder search | `Back to preview | Issue Assets` | Legacy-looking and not friendly when Holders is a top-nav item. |
| Holder detail | `Back to Report` plus `Back to Holders` | Useful when entered from reports, but can stack back links. |
| Receipts list | `Back to Report` plus `Back to Dashboard` | Duplicates global nav and mixes return context with safe fallback. |
| Receipt detail | `Back to Dashboard`, PDF, send/resend | Local action row is useful but mixes navigation and delivery actions. |
| Report | `Back to Dashboard`, utilities | Back link duplicates top nav; utilities are useful. |
| Asset search | `Back to Report` only when return target exists | Good contextual return behavior. |
| Admin pages | `Back to Admin Tools` or `Back to Dashboard` | Generally clear; repeated across admin surfaces. |
| Direct Add Assets | lock status, queue entry, clear queue, Preview Queue | Direct-only; still visually dense. |
| Generic preview | commit plus legacy Issue Mode branch | Direct-only; most legacy/bloated workflow surface. |

Local nav bloat is mostly from repeated "Back" affordances and legacy preview
links. Back links are safe, but they compete with next-step actions when they
appear at the top of active workflow pages.

## 4. Duplicate Or Low-Value Links

| Link/action | Where | Risk | Recommendation |
| --- | --- | --- | --- |
| Dashboard `Open Issue Workflow` | Dashboard and top nav | low | Keep; primary action duplication is useful. |
| Dashboard `Open Return Workflow` | Dashboard and top nav | low | Keep; primary action duplication is useful. |
| Dashboard `View Current Custody` | Dashboard and Reports top nav | low-medium | Keep for now; consider if dashboard card count is reduced. |
| `Back to Dashboard` | Report, receipts, receipt detail, admin tools | low | Consider demoting only in page-specific cleanup. |
| `Back to Report` plus `Back to Dashboard` | Receipts and holder/case drilldowns | medium | Consider one contextual return plus global nav, not both everywhere. |
| `Back to preview | Issue Assets` | Holder search | medium | Follow-up candidate; this feels legacy and preview-centered. |
| `Back to Batch Preview` | Issue preview | medium | Follow-up candidate; Issue preview should not feel subordinate to generic preview. |
| Generic `Issue Mode` card | `/preview` | medium-high | Keep direct-only; review separately before deployment. |
| Admin Tools intro sentence | Admin Tools page | low | Candidate to remove or convert to heading/status. |
| Dashboard intro and Custody Map helper text | Dashboard | low-medium | Candidate for text minimization, not nav behavior change. |

## 5. Unfriendly Labels

These labels are not wrong, but they may be less field-friendly:

| Label | Surface | Concern | Follow-up direction |
| --- | --- | --- | --- |
| Reports | top nav | Broad: includes status, receipts, search, cases, holders. | Recon/test whether `Status` or `Lookup` is clearer before renaming. |
| Review case space | Dashboard | "Space" is less direct than storage/case status. | Consider `Review cases` or `Case status`. |
| Open Operational Report | Admin Tools | Long and admin-sounding. | Consider `Admin report`. |
| Manage Organizations and Buildings | Admin Tools | Clear but long. | Consider grouping under `Setup Data`. |
| Create empty slots | Admin Tools | Technically accurate. | Leave unless grouped under Storage. |
| Assign unslotted asset | Admin Tools | Accurate but technical. | Leave unless grouped under Storage. |
| Receipt CC Settings | Admin Tools | Accurate admin delivery metadata label. | Leave. |
| Back to Batch Preview | Issue preview | Legacy/generic wording. | Review with generic preview cleanup. |
| Stage in queue | Direct Add Assets | Accurate but less normal than Issue/Return queue wording. | Direct-only; do not prioritize unless direct Add Assets remains in use. |
| Preview Queue | Direct Add Assets | Direct-only legacy wording. | Keep hidden from normal navigation. |

Guidance: prefer clearer headings and labels over adding helper paragraphs.
Do not add more explanatory block text unless it prevents operator error.

## 6. Hidden/Direct-Only Routes To Preserve

Keep these hidden from normal operator navigation:

| Route | Reason |
| --- | --- |
| `/add-assets` | Manual Add Assets remains direct-URL available only. |
| `/add-assets/review` | Direct Add Assets review path. |
| `/preview` | Generic preview; direct/legacy path, not workflow entry. |
| `/preview/validate` | Validation endpoint. |
| `/preview/mode` | Legacy Issue mode toggle. |
| `/preview/discard` | Generic batch discard. |
| `/preview/commit` | Generic commit path. |
| `/lock` | Local lock action for direct Add Assets. |
| `/bootstrap/admin` | Setup-only route. |
| `/demo` and `/demo/send-sample-receipt` | Isolated demo routes. |
| `/admin/assets/new` | Admin asset creation; do not mix with operator nav. |
| `/admin/assets/edit` | Admin asset maintenance. |
| `/admin/assets/retire` | Admin asset retirement. |
| `/admin/assets/replace` | Admin replacement workflow. |
| `/admin/assets/create` | Admin API endpoint. |
| `/admin/events/correct` | Event correction API. |
| `/admin/slot-move` | Admin slot maintenance. |
| `/admin/force-vacate` | Admin slot maintenance. |
| `/receipts/<id>/resend` GET | Redirect guard. |

Known constraints preserved:

- Manual Add Assets launchers stay hidden from normal navigation.
- `/add-assets` remains direct-URL available.
- Import/upload paths remain intact.
- `/issue` and `/return` must render workflow pages directly.
- Workflow entry routes must not redirect to preview.
- Preview assumes a populated queue.
- Admin-only maintenance must not mix with normal operator actions.

## 7. Bloat Candidates By Risk Level

### Low Risk: Presentation-Only Cleanup Later

- Remove or shorten broad intro copy when headings already carry meaning.
- Demote repeated `Back to Dashboard` where global nav already provides Dashboard.
- Shorten Admin Tools intro.
- Group Admin Tools links under headings without changing destinations.
- Tighten Dashboard helper text around Custody Map.

### Medium Risk: Needs Focused Follow-On And Manual Clickthrough

- Put `Admin Tools` first in the Admin dropdown.
- Rename `Reports` only after operator validation.
- Simplify holder search local nav.
- Rework Issue preview `Back to Batch Preview` wording/placement.
- Reduce dashboard card count or split lookup cards from action cards.
- Move receipt/report utilities around.

### High Risk: Recon First, Then Workflow Smoke Tests

- Any change that affects `/issue`, `/return`, `/issue/preview`, `/return/preview`, queue actions, or commit actions.
- Any redirect change on workflow entry routes.
- Any attempt to remove or disable `/add-assets`, `/preview`, or generic commit paths.
- Any move that exposes admin maintenance in normal operator navigation.
- Any change that weakens role boundaries or recovery/send blocking.

Navigation changes affecting workflows require manual operator smoke tests.

## 8. Recommended Streamline Order

1. Preserve primary operator nav:

   ```text
   Dashboard -> Issue -> Return -> Holders -> Reports
   ```

2. Keep these as dashboard secondary actions:

   ```text
   Issue, Return, Current Custody, Case Status, Asset Search
   ```

3. Keep Admin as a separate top-nav dropdown, with this recommended order:

   ```text
   Admin Tools -> Users -> Reference Data -> Import Holders -> Operational Report -> Restore Database
   ```

4. Group Admin Tools page links:

   ```text
   Access
   Setup Data
   Storage
   Delivery
   Reports And Backup
   Recovery
   ```

5. Keep direct-only/legacy workflow routes hidden:

   ```text
   /add-assets, /preview, preview POST endpoints, admin maintenance APIs
   ```

6. Handle bloat before copy:

   ```text
   remove/demote duplicate links -> clarify headings -> add helper text only if needed
   ```

## 9. Small Follow-On Issues

1. **Issue 27-156A: Group Admin Tools without changing destinations**
   - Scope: `admin_system.html` presentation only.
   - Goal: separate Access, Setup Data, Storage, Delivery, Reports/Backup, Recovery.
   - Verification: admin clickthrough; no workflow changes.

2. **Issue 27-156B: Simplify holder search local navigation**
   - Scope: holder search top local links only.
   - Goal: remove preview-centered feel while preserving Issue return paths.
   - Verification: select holder for Issue, add holder, clear search, normal holder lookup.

3. **Issue 27-156C: Review Issue preview relationship to generic Batch Preview**
   - Scope: recon or label-only follow-on first.
   - Goal: avoid making Issue preview feel like a branch under legacy `/preview`.
   - Verification: Issue queue -> preview -> commit smoke.

4. **Issue 27-156D: Dashboard action-card trim**
   - Scope: dashboard card hierarchy only.
   - Goal: make Issue/Return dominant; demote lookup/report cards if needed.
   - Verification: dashboard clickthrough plus Issue/Return smoke.

5. **Issue 27-156E: Decide whether Reports should be renamed**
   - Scope: recon/operator validation before code.
   - Goal: determine whether `Reports`, `Status`, or `Lookup` best matches field expectation.
   - Do not implement without confirming receipts/search/cases remain discoverable.

6. **Issue 27-156F: Direct Add Assets/generic preview bloat recon**
   - Scope: direct-only `/add-assets` and `/preview` surfaces.
   - Goal: decide whether to keep, compress, or further hide legacy batch surfaces.
   - Do not change import/upload paths.

7. **Issue 27-156G: Back-link consistency pass**
   - Scope: local back links on report, receipt, holder, case, and admin pages.
   - Goal: keep contextual return links where useful; avoid duplicate safe-page links competing with primary actions.

## Verification Notes

Inspected:

- `assettrack/intake/templates/base.html`
- `assettrack/intake/templates/dashboard.html`
- `assettrack/intake/templates/return_queue.html`
- `assettrack/intake/templates/issue_preview.html`
- `assettrack/intake/templates/return_preview.html`
- `assettrack/intake/templates/holders_search.html`
- `assettrack/intake/templates/holder_detail.html`
- `assettrack/intake/templates/report_readonly.html`
- `assettrack/intake/templates/receipts_list.html`
- `assettrack/intake/templates/receipt_detail.html`
- `assettrack/intake/templates/asset_search.html`
- `assettrack/intake/templates/index.html`
- `assettrack/intake/templates/preview.html`
- `assettrack/intake/templates/dashboard_case_detail.html`
- `assettrack/intake/templates/admin_system.html`
- `assettrack/intake/app.py` route definitions
- prior recon docs for menu order, text minimization, and Add Assets footprint

No implementation was performed.
