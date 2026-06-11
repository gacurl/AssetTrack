# Issue 27-149 Recon: Repeated Copy And Deletion Candidates

## Answer

Recommended next implementation issue: remove the smallest low-risk set of
helper paragraphs from holder detail, receipt detail, admin users, and admin
slot assignment.

Why it matters: those paragraphs repeat headings, buttons, or tables. Removing
them reduces reading load without touching routes, permissions, workflow order,
event semantics, receipt truth, or persistence.

## Scope

Recon only. No implementation was performed.

Change class for any later implementation: Class 1 -- UI / Presentation.

Do not combine a future copy cleanup issue with route, navigation, permission,
schema, custody, receipt, event, backup/restore, import, Issue, Return, preview,
queue, or commit behavior changes.

## Pages Reviewed

Operator-facing and shared pages:

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
- `assettrack/intake/templates/dashboard_holders.html`
- `assettrack/intake/templates/dashboard_holder_detail.html`
- `assettrack/intake/templates/dashboard_cases.html`
- `assettrack/intake/templates/dashboard_case_detail.html`
- `assettrack/intake/templates/403.html`
- `assettrack/intake/templates/404.html`
- `assettrack/intake/templates/account_change_password.html`

Admin/operator-shared maintenance pages:

- `assettrack/intake/templates/admin_system.html`
- `assettrack/intake/templates/admin_users.html`
- `assettrack/intake/templates/admin_reference_data.html`
- `assettrack/intake/templates/admin_receipt_cc.html`
- `assettrack/intake/templates/admin_holder_import.html`
- `assettrack/intake/templates/admin_db_restore.html`
- `assettrack/intake/templates/admin_new_asset.html`
- `assettrack/intake/templates/admin_edit_asset.html`
- `assettrack/intake/templates/admin_assign_slot.html`
- `assettrack/intake/templates/admin_slot_provision.html`
- `assettrack/intake/templates/admin_retire_asset.html`
- `assettrack/intake/templates/admin_replace_asset.html`
- `assettrack/intake/templates/admin_slot_move.html`
- `assettrack/intake/templates/admin_force_vacate.html`

Related recon reviewed:

- `docs/recon/issue-27-137-ui-text-minimization-and-edge-cases.md`
- `docs/recon/issue-27-148-menu-order-navigation-simplicity.md`
- `docs/recon/issue-27-156-app-bloat-navbar-friendliness.md`
- `docs/recon/issue-27-162-reports-label-decision.md`

## Repeated Or Stale Copy Found

| Page | Copy | Finding | Risk if removed |
| --- | --- | --- | --- |
| `return_queue.html` | "Stage scans in the queue, then review the batch before commit." | Repeats queue controls and Review button on both Issue and Return entry surfaces. | Low, if headings/buttons remain. |
| `issue_preview.html` | "Commit only after the holder, current location, and queued assets are fully reviewed." | Repeats preview cards and required commit checkboxes. | Medium; commit intentionality still needs checkbox text. |
| `return_preview.html` | "Commit only after the queued returns and any blocked items have been reviewed." | Repeats preview status, blocked-items card, and required checkbox. | Medium; do not remove in same issue as Issue copy unless tests are focused. |
| `holder_detail.html` | "Review the assigned asset(s) below." | Repeats the summary count and Assets In Custody table. | Low. |
| `holder_detail.html` | "Use this list to review what the holder has before selecting the next workflow action." | Repeats the Assets In Custody heading/table and header actions. | Low. |
| `receipt_detail.html` | "Review this only if something looks wrong. Each row shows the asset, movement, holder context, and home slot." | Repeats the Assets heading and table columns. | Low. |
| `admin_users.html` | "Create accounts here, then manage account state and password resets from the user list below." | Repeats Create User form and Users table/actions. | Low. |
| `admin_assign_slot.html` | "Select an unslotted asset." | Repeats Unslotted Assets heading and Assign buttons. | Low. |
| `asset_search.html` | "Search by asset tag or serial number. If both are entered, asset tag is used first." | Mostly useful, but partly competes with labels. | Medium; "asset tag is used first" is behavior guidance. |
| `admin_new_asset.html` | "Fill in the required fields below. Asset type defaults to Laptop." | First sentence repeats required labels; second sentence explains default. | Medium; can shorten later, not delete blindly. |
| `admin_reference_data.html` | Three card intros explaining downstream use. | Repeats form headings but also explains reference-data impact. | Medium; shorten, do not delete as a batch. |
| `admin_retire_asset.html` | Search instructions for full/partial tag and select behavior. | Explains lookup behavior shared by admin asset maintenance. | Medium; could become shorter, but not a first deletion. |
| `admin_edit_asset.html` | Asset removal paragraphs repeat retire-flow direction. | The page says removal is not exposed in multiple ways. | Medium-high; content protects audit-safe removal posture. |

## Safe Deletion Candidates

These are safe candidates for a small implementation issue because nearby
headings, labels, buttons, or tables already carry the same meaning.

| Page | Candidate | Why safe |
| --- | --- | --- |
| `holder_detail.html` | Remove the summary note under "Assets currently assigned". | Count and table already show whether assets exist. |
| `holder_detail.html` | Remove the `holder-assets-intro` paragraph under "Assets In Custody". | The heading and table columns already explain the content. |
| `receipt_detail.html` | Remove the `receipt-assets-lead` paragraph under "Assets". | Table columns already show asset, movement, holder, and home slot. |
| `admin_users.html` | Remove the Create User `card-intro`. | The form and Users table/action labels already explain create/manage flow. |
| `admin_assign_slot.html` | Remove "Select an unslotted asset." | The "Unslotted Assets" heading and Assign buttons carry the action. |

Recommended first implementation shape:

- Scope only the five deletions above.
- Do not touch workflow entry, preview, receipt delivery status, recovery text,
  role text, or navigation.
- Verification should be focused on holder detail, receipt detail, admin users,
  and admin assign-slot rendering.

## Candidates Needing Separate Implementation Issues

These need their own small issues because they sit near workflow safety,
receipt/recovery truth, admin maintenance, or reference-data meaning.

| Candidate | Why separate |
| --- | --- |
| Compress Issue/Return scan-card intro in `return_queue.html`. | It appears on workflow entry pages and references queue/review/commit. Keep the required seam explicit and test Issue/Return entry. |
| Compress Issue Preview commit intro in `issue_preview.html`. | It sits directly above commit checkboxes. Preserve commit intentionality and holder/current-location review. |
| Compress Return Preview ready/commit copy in `return_preview.html`. | Return destination/home-slot wording protects custody clarity. |
| Shorten `asset_search.html` helper text. | "Asset tag is used first" documents current lookup behavior; changing it is wording-only but should be tested with asset-search UI tests. |
| Shorten `admin_reference_data.html` intros. | Reference values affect operator location selection and maintenance forms. |
| Shorten `admin_receipt_cc.html` clear/fallback wording. | CC is delivery metadata only; blank save behavior and environment fallback should stay clear. |
| Compress admin asset creation/edit/retire/replace helper copy. | These pages protect audit-safe asset maintenance and terminal retirement/replacement behavior. |
| Compress restore/recovery page text. | Recovery copy is intentionally verbose at a live DB replacement boundary. |
| Review 403/404 safe-next-step copy. | Safe fallback destinations intersect with hidden Manual Add Assets and auth state. |

## Copy That Should Stay

Safety-critical copy:

- Required Issue/Return commit checkboxes.
- Empty queue, invalid scan, blocked item, invalid holder, invalid location,
  inactive-holder, locked-session, and password-change-required messages.
- Admin temporary-password "shown once" warning and disabled-account warning.
- Admin retire/replace confirmation and terminal/atomic-operation warnings.
- Force-vacate warning requiring physical verification.

Custody-critical copy:

- `issue_preview.html`: "Holder is the custody actor. Location and case/slot are context only."
- Issue current-location prerequisite and holder-organization building constraint.
- `return_preview.html`: return destination/home-slot wording.
- Receipt status lines that say custody is already recorded.
- Holder follow-up email disclaimer: manual reminders do not record or change custody.
- Receipt list explanation for per-asset return locations.
- Dashboard custody map disclaimer that the map is read-only orientation and not custody state.

Recovery-critical copy:

- Global recovery banner.
- Admin recovery state, rollback artifact, restore history, and parse-error text.
- Restore validation-before-replacement text.
- "No live replacement has occurred yet."
- Confirm-live-replacement text explaining rollback copy, recovery mode, and restore history.
- After Restore checklist.
- Receipt resend/retry paused during recovery mode.

Why it matters: these lines prevent operators from confusing UI convenience with
custody truth, receipt delivery with custody recording, or recovery metadata with
event/audit history.

## Recommended Next Implementation Issue

**Issue 27-149A: Delete low-value helper paragraphs only**

Class: Class 1 -- UI / Presentation.

Scope:

- `assettrack/intake/templates/holder_detail.html`
- `assettrack/intake/templates/receipt_detail.html`
- `assettrack/intake/templates/admin_users.html`
- `assettrack/intake/templates/admin_assign_slot.html`

Allowed edits:

- Delete only the five safe deletion candidates listed above.
- Do not rewrite surrounding headings, labels, buttons, tables, routes, or tests
  unless a focused rendering test must be updated for removed text.

Not allowed:

- Do not change workflow copy near Issue/Return entry, preview, or commit.
- Do not change receipt delivery status or recovery-mode copy.
- Do not change admin recovery/restore, retire, replace, force-vacate, schema,
  permission, custody, receipt, event, queue, preview, or commit behavior.

## Future Focused Test Commands

If Issue 27-149A is implemented, run:

```bash
python3 -m compileall assettrack tests
```

Focused pytest commands likely relevant after that implementation:

```bash
pytest tests/test_holder_creation_viability.py::test_holder_detail_from_report_keeps_back_link_but_not_report_action_return_to tests/test_holder_followup_email.py tests/test_receipt_detail.py::test_receipt_detail_renders_stored_snapshot tests/test_admin_user_management.py tests/test_admin_slot_provision.py -q
```

If a later implementation touches workflow entry or preview copy, run:

```bash
pytest tests/test_issue_23_2_preview_commit_seam.py tests/test_issue_holder_prerequisite.py tests/test_return_batch.py -q
```

If a later implementation touches Reports, receipts list, or asset search copy,
run:

```bash
pytest tests/test_admin_system_health.py::test_operator_report_is_actionable_with_safe_drill_in_links tests/test_admin_system_health.py::test_report_drill_ins_show_back_to_report_only_for_safe_report_context tests/test_receipts_list.py tests/test_asset_search_ui.py -q
```

## Verification Notes

This recon issue changed documentation only.

Manual verification:

- Confirm only `docs/recon/issue-27-149-repeated-copy-deletion-candidates.md`
  changed.
- Confirm no templates, routes, permissions, schema, custody logic, event
  history, persistence, receipt behavior, backup/restore behavior, import
  behavior, Issue workflow, Return workflow, preview behavior, queue behavior, or
  commit behavior changed.
