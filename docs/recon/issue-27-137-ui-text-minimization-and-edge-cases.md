# Issue 27-137 Recon: UI Text Minimization and Edge Cases

## Scope

Recon only.

- No template, route, CSS, test, schema, persistence, custody, receipt, audit-history, event-history, auth, or workflow behavior changes.
- Potential future impact: Class 1 -- UI / Presentation.
- Purpose: identify excess operator-facing wording and protect wording that is required for safety, recovery, or custody clarity.

Why it matters:

AssetTrack is used in field conditions. The interface should rely on headings, labels, buttons, status chips, alerts, and required notices. Paragraphs should stay only when they prevent unsafe action, explain recovery, or protect custody meaning.

## Sources Reviewed

- `AGENTS.md`
- `docs/codex/PROJECT_MEMORY.md`
- `docs/codex/CURRENT_STATE.md`
- `docs/recon/issue-27-73-workflow-surface-compression.md`
- `docs/recon/issue-27-136-add-assets-removal-footprint.md`
- `assettrack/intake/app.py`
- `assettrack/intake/templates/base.html`
- `assettrack/intake/templates/dashboard.html`
- `assettrack/intake/templates/index.html`
- `assettrack/intake/templates/preview.html`
- `assettrack/intake/templates/return_queue.html`
- `assettrack/intake/templates/issue_preview.html`
- `assettrack/intake/templates/return_preview.html`
- `assettrack/intake/templates/holders_search.html`
- `assettrack/intake/templates/holder_detail.html`
- `assettrack/intake/templates/receipts_list.html`
- `assettrack/intake/templates/receipt_detail.html`
- `assettrack/intake/templates/admin_system.html`
- `assettrack/intake/templates/admin_users.html`
- `assettrack/intake/templates/admin_reference_data.html`
- `assettrack/intake/templates/admin_holder_import.html`
- `assettrack/intake/templates/admin_db_restore.html`
- `assettrack/intake/templates/403.html`
- `assettrack/intake/templates/404.html`
- `assettrack/intake/templates/account_change_password.html`

## Classification Rules Used

| Classification | Meaning |
| --- | --- |
| remove wording later | Text can be removed without losing operator action, safety, recovery, or custody meaning. |
| shorten wording later | Text carries some value but can become shorter status/label wording. |
| keep because safety requires it | Text prevents unsafe commit, unsupported action, invalid selection, or auth/session confusion. |
| keep because recovery requires it | Text explains restore, rollback, recovery mode, or receipt delivery blocking. |
| keep because custody clarity requires it | Text distinguishes custody actor, location context, receipt truth, or manual reminders. |
| convert to button/label/status wording later | Text should move from sentence/paragraph form into heading, chip, label, button, or status line. |
| needs separate issue | Finding is not safe to bundle into general copy cleanup. |

## Screen Findings

### Dashboard

| Surface | Finding | Classification | Later action |
| --- | --- | --- | --- |
| `dashboard.html` intro | "Calm operational state first..." is tone-setting copy, not operational state. | remove wording later | Remove or replace with a status chip if a real state exists. |
| `dashboard.html` custody map note | "read-only orientation only" and "does not create custody state" protects custody semantics. | keep because custody clarity requires it | Preserve, but shorten to "Read-only orientation. Not custody state." |
| Primary dashboard cards | "Assets currently..." repeats the labels and numbers. | shorten wording later | Convert to compact labels: "In custody", "In storage", "Recorded". |
| Issue/Return action cards | "Start the ... workflow..." repeats the buttons. | convert to button/label/status wording later | Let `Open Issue Workflow` and `Open Return Workflow` carry the action. |
| Custody map summary | "Thread -> Building -> Operational Domain -> Custody Holder -> Asset" is dense but useful orientation. | shorten wording later | Keep as a compact hierarchy label. |
| Problems / empty states | "No current problems", "No unslotted assets", "No slot conflicts detected" are useful status messages. | keep because safety requires it | Preserve as status text. |

### Add Assets / Generic Preview

| Surface | Finding | Classification | Later action |
| --- | --- | --- | --- |
| `index.html` lock summary | "Enter access code to unlock" is a recovery/action cue for locked state. | keep because safety requires it | Keep, or make it a compact locked-state status. |
| `index.html` card intro | "Add assets to the queue, then review..." duplicates the workflow controls. | shorten wording later | Convert to `Queue -> Preview -> Commit` status wording. |
| `index.html` asset-type helper | "Applies to assets created from this queued batch" clarifies scope. | keep because custody clarity requires it | Preserve, possibly shorten to "Applies to this batch." |
| `preview.html` Batch Status | Rows, equipment type, and valid/not valid are good status content. | keep because safety requires it | Preserve as status line. |
| `preview.html` commit checkbox | Review acknowledgment protects commit intentionality. | keep because safety requires it | Preserve. |
| `preview.html` Issue Mode card | Legacy Issue-mode explanation and links make preview behave like a branching hub. | needs separate issue | Handle with the Add Assets/legacy preview footprint work, not general text cleanup. |

### Issue Workflow

| Surface | Finding | Classification | Later action |
| --- | --- | --- | --- |
| `return_queue.html` Issue current-location status | "Set where these assets are leaving from before scanning" is prerequisite guidance. | keep because custody clarity requires it | Preserve as a prerequisite status. |
| Issue location organization note | "Building choices are limited..." explains why options may be missing. | keep because safety requires it | Preserve, shorten to "Holder organization limits buildings." |
| Scan card intro | "Stage scans in the queue, then review..." repeats workflow controls. | shorten wording later | Convert to a smaller status label or remove when the queue is visible. |
| Issue workflow flashes | "Select a holder before issuing assets", current-location errors, invalid scan messages are required. | keep because safety requires it | Preserve clear blocked-state messages. |
| Workflow banner + holder card + current-location card | Holder/location facts are repeated across banner and review cards. | shorten wording later | Keep facts, reduce repeated explanatory sentences. |
| `issue_preview.html` holder note | "Holder is the custody actor. Location and case/slot are context only" is custody-critical. | keep because custody clarity requires it | Preserve unless replaced by an equally explicit status label. |
| `issue_preview.html` commit intro | "Commit only after..." duplicates required checkboxes but frames final safety. | shorten wording later | Shorten to "Final review required." |

### Return Workflow

| Surface | Finding | Classification | Later action |
| --- | --- | --- | --- |
| `return_queue.html` recent return flash | "Verify home slots" is a recovery/follow-up cue after returns. | keep because safety requires it | Preserve, maybe label as "Next: verify home slots". |
| Return scan card intro | Same duplicated queue/review sentence as Issue. | shorten wording later | Convert to compact workflow status. |
| Return queue empty state | "No assets queued" is useful status. | keep because safety requires it | Preserve. |
| `return_preview.html` readiness intro | "Returns go to each asset's assigned home slot. Review..." is safety-critical destination guidance. | keep because custody clarity requires it | Preserve, but it can become "Destination: assigned home slot. Review before commit." |
| `return_preview.html` commit checkbox wording | Review and responsibility acknowledgment protect commit intentionality. | keep because safety requires it | Preserve. |

### Holder Pages

| Surface | Finding | Classification | Later action |
| --- | --- | --- | --- |
| `holders_search.html` top paragraph nav | "Back to preview | Issue Assets" appears as paragraph navigation outside the normal nav pattern. | convert to button/label/status wording later | Move to a local nav/action row in a follow-on issue. |
| Holder search label | "Search by person name, group, organization, or identifier" is useful but long. | shorten wording later | Use "Search holders" label plus placeholder examples. |
| Assignment-only hidden inactive note | "Inactive holders are hidden..." explains a missing-result edge case. | keep because safety requires it | Preserve, or convert to a filter status chip. |
| Selected holder card | Current selection, identity, organization, identifier, email are custody context. | keep because custody clarity requires it | Preserve. |
| `holder_detail.html` asset summary note | "Review the assigned asset(s) below" repeats the table. | remove wording later | Remove; the count and table carry the action. |
| Follow-up email note | "manual reminders... do not record or change custody" is custody-critical. | keep because custody clarity requires it | Preserve exactly in substance. |
| Assets in custody intro | "Use this list..." is helper copy that the heading/table already imply. | remove wording later | Remove or shorten to a table caption if needed. |

### Receipt Pages

| Surface | Finding | Classification | Later action |
| --- | --- | --- | --- |
| `receipts_list.html` search/results | Mostly labels, table headers, status chips, and search-match labels. | keep because recovery requires it | Preserve searchable receipt recovery surface. |
| Receipt list "See the receipt details..." | Explains why return location summary varies by asset. | keep because custody clarity requires it | Preserve, shorten to "Per-asset destinations in detail." |
| `receipt_detail.html` custody status line | "custody already recorded" prevents confusion between receipt delivery and custody truth. | keep because custody clarity requires it | Preserve. |
| Receipt context line | Dense holder/location/time/operator/email line is useful but long. | shorten wording later | Split into compact labeled facts or status chips. |
| Manual holder follow-up note | Distinguishes follow-up email from receipt/custody. | keep because custody clarity requires it | Preserve. |
| Recovery-mode receipt block | Explains paused resend/retry actions. | keep because recovery requires it | Preserve. |
| Assets lead | "Review this only if something looks wrong..." is nonessential helper copy. | remove wording later | Remove; table heading and rows are enough. |
| Technical details | Collapsed extra facts are appropriate for recovery/audit review. | keep because recovery requires it | Preserve collapsed state. |

### Admin Navigation and Maintenance

| Surface | Finding | Classification | Later action |
| --- | --- | --- | --- |
| `base.html` admin menu | Admin destinations are labels, not paragraphs. | keep because safety requires it | Preserve role-gated navigation; any Add Assets link decision belongs to Issue 27-136 follow-on. |
| Global recovery banner | "Recovery acknowledgment is required..." protects blocked receipt actions. | keep because recovery requires it | Preserve. |
| `admin_system.html` Admin Tools intro | "Use these tools..." repeats the grid and is broad. | shorten wording later | Replace with status label or remove. |
| Recovery state tables | Status, acknowledgment, paths, rollback, history are recovery-critical. | keep because recovery requires it | Preserve. |
| Restore history text | "Operational restore records only..." distinguishes restore metadata from custody/audit history. | keep because recovery requires it | Preserve, possibly shorten. |
| `admin_users.html` temporary password note | "shown once... trusted local channel" is security-critical. | keep because safety requires it | Preserve. |
| `admin_users.html` create-user intro | Repeats the form/table relationship. | remove wording later | Remove. |
| Disabled-temp-password note | Explains why login still fails. | keep because safety requires it | Preserve. |
| `admin_reference_data.html` card intros | Explain downstream use of reference values. | shorten wording later | Convert to compact labels/status hints. |

### Upload / Import / Restore

| Surface | Finding | Classification | Later action |
| --- | --- | --- | --- |
| `admin_holder_import.html` CSV requirements | Required columns and update/create behavior are import-critical. | keep because safety requires it | Preserve in disclosure. |
| Holder import result summary | Processed/created/updated/errors are concise and useful. | keep because recovery requires it | Preserve. |
| Holder import flash + result card | Same import result may appear twice. | shorten wording later | In a follow-on, keep flash for immediate status and result card for details, or merge carefully. |
| `admin_db_restore.html` restore intro | Validation-before-replacement and password-confirmation text is recovery-critical. | keep because recovery requires it | Preserve. |
| Validation summary notice | "No live replacement has occurred yet" prevents unsafe assumptions. | keep because recovery requires it | Preserve. |
| Confirm live replacement paragraph | Explains rollback, recovery mode, and restore history before destructive action. | keep because recovery requires it | Preserve. |
| After Restore checklist | Long, but it is runbook content at a recovery boundary. | keep because recovery requires it | Preserve or move to linked runbook only in a dedicated recovery UX issue. |

### Error and Blocked States

| Surface | Finding | Classification | Later action |
| --- | --- | --- | --- |
| `403.html` | Two paragraphs explain access denial and recovery path. | keep because safety requires it | Preserve; can shorten to "Access denied. Use Dashboard or correct account." |
| `404.html` | Safe-next-step paragraph is useful recovery from dead routes. | keep because recovery requires it | Preserve; direct unauthenticated fallback to `/add-assets` should be reviewed with Issue 27-136 route/link decisions. |
| `account_change_password.html` | Password-change-required flash and password rule are security-critical. | keep because safety requires it | Preserve. |
| Locked-session flashes | "Locked. Re-enter access code." appears across workflows. | keep because safety requires it | Preserve. |
| Empty queue preview redirects | "Queue is empty..." messages prevent invalid preview/commit expectations. | keep because safety requires it | Preserve. |
| Receipt recovery blocks | Recovery-mode resend/retry blocks prevent delivery actions during recovery. | keep because recovery requires it | Preserve. |

## Edge Cases and Dead Ends

| Edge case | Evidence | Classification | Why it matters | Follow-on |
| --- | --- | --- | --- | --- |
| Blocked item details may be hidden on Issue Preview. | `issue_preview.html` renders blocked issues inside `<ul><template>...</template></ul>`. | needs separate issue | The page can show `Needs Review` without visible blocked details. Commit-time revalidation still protects event history, but operator recovery is weaker. | Open high-priority Class 1 issue to render blocked issue text visibly on Issue Preview without changing validation or commit behavior. |
| Blocked item details may be hidden on Return Preview. | `return_preview.html` uses the same `<ul><template>...</template></ul>` pattern for blocked issues and per-row asset issues. | needs separate issue | Return commit remains blocked when `blocking_issues` exists, but the operator may not see what to fix. | Open high-priority Class 1 issue to render blocked return details visibly. |
| Issue preview can show several holder/location edit paths. | Workflow banner, Holder card, and Current Location card can all present context/actions. | shorten wording later | Too many secondary actions can compete with final review. | Combine secondary review actions in a presentation-only issue. |
| Holders search uses paragraph navigation. | `holders_search.html` top line mixes "Back to preview" and "Issue Assets". | convert to button/label/status wording later | Paragraph nav is noisy and can be ambiguous when arriving from reports or Issue. | Standardize holder local nav in a small Class 1 issue. |
| 404 unauthenticated safe page points to Add Assets. | `404.html` fallback uses `add_assets` when not authenticated. | needs separate issue | Add Assets visibility is already under review; changing fallback destination must not be bundled into text minimization. | Handle with Issue 27-136 follow-on or a dedicated safe-fallback issue. |
| Admin restore page carries runbook-length text. | `admin_db_restore.html` After Restore checklist. | keep because recovery requires it | Long text is justified at live DB replacement boundary. | Only move/shorten in a dedicated recovery UX issue with smoke-test coverage. |

No edge case found in this recon requires immediate implementation inside Issue 27-137 because this issue explicitly forbids implementation. The hidden blocked-item rendering findings should be split into a high-priority follow-on because they affect operator recovery, while existing commit revalidation still protects event history.

## Wording Cleanup Candidates

Remove later:

- Dashboard tone-setting intro.
- Dashboard action-card helper sentences that repeat Issue/Return buttons.
- Holder detail assigned-assets helper sentence.
- Holder detail assets-table intro.
- Receipt detail assets lead sentence.
- Admin Users create-user intro.

Shorten later:

- Dashboard primary-card copy.
- Custody map orientation text.
- Add Assets queue/review intro.
- Issue and Return scan card intros.
- Issue Preview commit intro.
- Receipt detail context line.
- Admin Tools intro.
- Admin Reference Data card intros.
- 403/404 safe-next-step paragraphs.

Convert to button/label/status wording later:

- Holder search top paragraph navigation.
- Dashboard action-card helper copy.
- Add Assets workflow intro.
- Issue/Return queue workflow helper copy.
- Recovery and import summaries where a status chip can carry the same information without losing meaning.

## Wording to Preserve

Safety-critical:

- Review and responsibility acknowledgment checkboxes before Issue/Return commit.
- Empty queue, invalid scan, invalid holder, invalid location, invalid slot, locked-session, auth, and password-change-required messages.
- Admin temporary-password one-time visibility and disabled-account warnings.
- Import required-column and validation failure messages.
- 403 access-denied recovery path.

Recovery-critical:

- Global recovery-mode banner.
- Admin recovery state, rollback, restore history, and parse-error messages.
- Restore validation-before-replacement and live replacement confirmation text.
- Receipt resend/retry blocks during recovery mode.
- Receipt delivery failure status and retry/resend action labels.

Custody-critical:

- "Holder is the custody actor. Location and case/slot are context only."
- Current location prerequisite and holder-organization building constraint.
- Return destination/home-slot wording.
- Receipt "custody already recorded" status.
- Holder follow-up email disclaimer: manual reminders do not record or change custody.
- Receipt location-varies-by-asset explanation.

## Proposed Follow-On Issues

1. **Issue 27-137A: Render preview blocked-item details visibly**
   - Class 1 -- UI / Presentation.
   - Scope: `issue_preview.html` and `return_preview.html` only.
   - Preserve validation, commit revalidation, route flow, and queue state.

2. **Issue 27-137B: Remove low-value dashboard and action-card helper copy**
   - Class 1 -- UI / Presentation.
   - Scope: dashboard paragraphs and repeated action-card copy.
   - Preserve read-only dashboard behavior.

3. **Issue 27-137C: Compress Issue/Return queue helper text**
   - Class 1 -- UI / Presentation.
   - Scope: scan-card intros and prerequisite status wording.
   - Preserve entry -> prerequisite -> queue -> preview -> commit.

4. **Issue 27-137D: Standardize holder navigation and remove holder helper paragraphs**
   - Class 1 -- UI / Presentation.
   - Scope: holder search/detail copy and local nav presentation.
   - Preserve holder selection, inactive-holder blocking, and return_to behavior.

5. **Issue 27-137E: Compress receipt detail copy without weakening custody or recovery truth**
   - Class 1 -- UI / Presentation.
   - Scope: receipt detail context and assets lead.
   - Preserve receipt snapshot truth, delivery status, recovery blocking, and manual follow-up disclaimer.

6. **Issue 27-137F: Trim admin helper copy outside recovery boundaries**
   - Class 1 -- UI / Presentation.
   - Scope: Admin Tools, Admin Users, and Admin Reference Data intros.
   - Exclude DB restore/recovery wording unless a dedicated recovery UX issue is opened.

7. **Issue 27-137G: Review unauthenticated safe fallback after Add Assets visibility decision**
   - Class 1 or Class 2 depending on route behavior.
   - Scope: `403.html` / `404.html` safe-page destination only after Issue 27-136 follow-on decides Add Assets reachability.

## Stop-Condition Review

- UI cleanup would require behavior changes in this issue: **No.**
- Safety-critical wording could not be classified: **No.**
- Recovery-critical wording could not be classified: **No.**
- Custody-critical wording could not be classified: **No.**
- Workflow edge cases require immediate implementation in this issue: **No.**
- Scope expanded beyond recon: **No.**
- Invariant weakened: **No.**

## Invariant Confirmation

This recon changed documentation only.

- No runtime behavior changed.
- No schema changed.
- No SQLite persistence changed.
- No custody truth changed.
- No receipt truth changed.
- No audit history changed.
- No event history changed.
- No route, template, validation, commit, or workflow behavior changed.
