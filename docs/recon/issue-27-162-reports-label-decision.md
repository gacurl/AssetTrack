# Issue 27-162 Recon: Reports Label Decision

## Answer

Recommendation: keep `Reports` for deployment.

Why it matters: `Reports` is not perfect, but it is the least risky current
top-level label for a read-only cluster that includes current state, receipts,
asset lookup, holder accountability, case accountability, and report-return
drilldowns. Renaming it now could make receipts or lookup harder to find without
proving that operators are confused by the current label.

## Scope

Recon only. No implementation was performed.

Reviewed:

- `assettrack/intake/templates/base.html`
- `assettrack/intake/templates/report_readonly.html`
- `assettrack/intake/templates/receipts_list.html`
- `assettrack/intake/templates/asset_search.html`
- `assettrack/intake/templates/dashboard_cases.html`
- `assettrack/intake/templates/dashboard_case_detail.html`
- `assettrack/intake/templates/dashboard_holders.html`
- `assettrack/intake/templates/dashboard_holder_detail.html`
- `assettrack/intake/app.py`
- `tests/test_basic_auth_guard.py`
- `tests/test_admin_system_health.py`
- `docs/recon/issue-27-148-menu-order-navigation-simplicity.md`
- `docs/recon/issue-27-156-app-bloat-navbar-friendliness.md`

## Current Reports Contents

Top nav:

| Surface | Label | Destination | Active State Also Covers |
| --- | --- | --- | --- |
| Primary operator nav | Reports | `/report` | `/receipts`, `/assets/search`, `/dashboard/holders`, `/dashboard/cases` |

The current operator nav order remains:

```text
Dashboard -> Issue -> Return -> Holders -> Reports
```

Routes and pages reachable from the Reports cluster:

| Item | Route | Page / Action | Role Surface |
| --- | --- | --- | --- |
| Current System State | `/report` | Operator-safe read-only state report | operator and admin |
| Active / retired inventory toggle | `/report?include_retired=1` and `/report` | Switches report scope | operator and admin |
| Open receipts | `/receipts?return_to=/report` | Receipt search/list | operator and admin |
| Receipt detail | `/receipts/<id>` | Stored receipt detail | operator and admin |
| Receipt PDF | `/receipts/<id>/pdf` | Download receipt PDF | operator and admin |
| Send receipt email | `/receipts/<id>/send` | Delivery action from receipt detail | operator and admin |
| Resend receipt email | `/receipts/<id>/resend` | Admin resend action / GET redirect guard | admin only |
| Asset search | `/assets/search?return_to=/report` | Asset lookup by tag or serial | operator and admin |
| Asset drilldown from report rows | `/assets/search?asset_tag=...&return_to=/report` | Asset lookup prefilled by report row | operator and admin |
| Holder drilldown from report rows | `/holders/<id>?return_to=/report` | Holder detail with Back to Report context | operator and admin |
| Holder accountability | `/dashboard/holders?return_to=/report` | Holders with assets out | operator and admin |
| Holder accountability detail | `/dashboard/holders/<id>?return_to=/report` | Outstanding assets for holder | operator and admin |
| Case accountability | `/dashboard/cases?return_to=/report` | Case space / slot status | operator and admin |
| Case accountability detail | `/dashboard/cases/<case>?return_to=/report` | Slot layout and selected-asset workflow launchers | operator and admin |

Related but separate admin report surface:

| Item | Route | Page / Action | Role Surface |
| --- | --- | --- | --- |
| Operational Report | `/admin/report` | Admin-only read-only operational report | admin only |
| Operational Report PDF | `/admin/report/pdf` | Admin-only PDF export | admin only |

## Operator-Facing Purpose

| Item | Operator Purpose |
| --- | --- |
| Current System State | See the current custody/storage picture without mutating state. |
| Active / retired inventory toggle | Include or hide retired assets while staying read-only. |
| Receipts list | Find custody receipts by asset, holder, or building/room. |
| Receipt detail / PDF | Recover, inspect, or provide proof of a committed custody action. |
| Send receipt email | Complete delivery after custody is already recorded. |
| Asset search | Quickly answer where an asset is and who currently holds it. |
| Holder drilldowns | Move from report rows into holder-specific accountability context. |
| Holder accountability | Find holders with assets currently out. |
| Case accountability | Review storage/case space and slot occupancy. |
| Case detail workflow launchers | Select assets from a case before entering Issue or Return review. |
| Admin operational report | Give admins broader read-only visibility and PDF/backup support outside normal operator nav. |

## Confusion Risks With Current Label

- `Reports` sounds like a document archive, but the cluster also contains live
  lookup tools: asset search, holder accountability, and case accountability.
- Operators looking for "Where is this asset?" may not naturally choose
  `Reports` unless they have learned that Current System State is the lookup
  hub.
- `Receipts` is intentionally not top-level, so operators must understand that
  receipt recovery lives under `Reports`.
- `Dashboard` also links to `Current Custody`, `Case Status`, and `Asset Search`,
  which can make `Reports` feel partly duplicated rather than clearly distinct.
- The page heading is `Current System State`, not `Reports`; that mismatch is
  acceptable but shows the label is a navigation bucket rather than the exact
  page title.

## Confusion Risks With Renaming

- `Status` would describe current state better, but it may hide receipts and
  receipt recovery because receipts are historical proof, not just status.
- `Lookup` would describe asset/search/drilldown behavior better, but it may
  hide the read-only report and receipt proof surfaces.
- `Records` could cover reports and receipts, but may sound like audit/event
  history and create unsafe expectations that operators are browsing custody
  truth directly.
- `Current State` would match the landing page, but it is longer and does not
  clearly include receipts.
- Any rename this close to deployment would require operator validation,
  navigation tests, and manual smoke testing to avoid hiding read-only recovery
  surfaces.
- Renaming without splitting the cluster would not reduce the underlying breadth:
  one top-level item would still cover report, receipts, asset search, holders,
  and cases.

## Decision

Keep `Reports`.

Reasoning:

- It is already the locked fifth item in the operator nav order.
- It is the least misleading single-word label for a broad read-only cluster.
- It correctly implies non-workflow, non-mutating review rather than Issue or
  Return action.
- Existing tests intentionally assert that `Receipts` is not top-level and that
  `Reports` follows Dashboard, Issue, Return, and Holders.
- The current label preserves deployment stability while the app is close to
  field use.

Do not rename `Reports` before deployment unless operator testing shows a clear
failure to find current state, receipts, or asset lookup.

## Suggested Follow-Up Issue

Only if operator validation shows confusion:

**Issue 27-162A: Validate Reports label with operators before any rename**

Scope:

- Ask operators where they would go to:
  - find a receipt
  - find an asset by tag
  - see who has assets out
  - review case space
  - see current custody
- Decide between keeping `Reports`, renaming to `Status`, renaming to `Lookup`,
  or splitting the cluster after deployment.
- Do not change routes, templates, permissions, schema, custody behavior, receipt
  behavior, event history, queues, preview, or commit behavior in the validation
  issue.

## Verification Plan

Requested command:

```bash
python3 -m compileall assettrack tests
```

Focused pytest, because existing tests cover current navigation naming/order and
Reports routing/drilldowns:

```bash
pytest tests/test_basic_auth_guard.py::test_preview_not_shown_in_main_navigation_but_direct_route_still_loads tests/test_admin_system_health.py::test_operator_report_is_actionable_with_safe_drill_in_links tests/test_admin_system_health.py::test_report_drill_ins_show_back_to_report_only_for_safe_report_context
```

Manual verification:

- Confirm only this recon document changed.
- Confirm no templates, routes, permissions, schema, custody logic, receipt
  logic, event history, persistence, import behavior, backup/restore behavior,
  Issue workflow, Return workflow, preview behavior, queue behavior, or commit
  behavior changed.
