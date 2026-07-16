# Barebones AssetTrack Application Boundary

Issue: 29-1
Classification: Class 2 - Logic / Behavior
Scope: planning and documentation only. No runtime behavior, schema, route, template, event, custody, receipt, email, persistence, dependency, or navigation logic changes are authorized here.

## Core Product Boundary

AssetTrack records:

- what equipment exists
- where each asset belongs
- who has it, when applicable
- its current status
- every custody, location, and status change
- email communication associated with Issue and Return custody actions

The smallest useful AssetTrack product is a local, role-protected, SQLite-backed custody system for field operators. It must support person-assigned laptops and location-assigned switches and routers without splitting them into separate systems.

The append-only event history remains the authoritative custody record. Email receipts communicate and document Issue and Return activity, but email delivery never creates, reverses, or modifies custody state. Delivery failure must not roll back committed events or receipt records.

## Current Application Posture After Milestone 27

Milestone 27 simplification work is visible in the current repository:

- Primary navigation is reduced to Dashboard, Issue, Return, Holders, Reports, Account, Logout, and an admin-only Admin menu.
- Manual Add Assets is hidden from normal navigation while `/add-assets` remains available directly.
- Issue and Return keep the required seam: entry, prerequisite selection, scan queue, preview, commit, receipt confirmation.
- Receipt, proof, and report access are consolidated mostly under Reports and contextual links.
- Admin Tools groups protected setup, storage, delivery, reporting, backup, and recovery tools.
- Recovery mode remains explicit and blocks resend/retry until admin acknowledgment.

This document does not recreate that work. It defines what remains core and where future reduction could happen without assuming hidden pages are unnecessary.

## Classification Key

- Keep visible: should remain easy to reach in primary navigation, a workflow step, an admin hub, or a contextual proof path.
- Keep but hide: should remain available by direct URL, contextual link, admin tool hub, CLI/script, or support workflow, but does not need primary navigation.
- Candidate for later removal: may be removable only by a separate approved issue after Greg confirms product, operational, security, schema, or audit consequences.

## Surface Inventory

| Feature or page | Route | Template or implementation | Current purpose | Audience | Laptop relevance | Network-device relevance | Custody relevance | Email-receipt relevance | Dependencies | Risks of hiding it | Risks of removing it | Classification | Future GitHub issue |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Login | `/` GET/POST | `assettrack/intake/app.py:intake`, `splash.html` | Local authentication entry. | Operators, admins | Required | Required | Protects custody routes | Protects receipt routes | `assettrack/users.py`, Flask session | Cannot use app | Breaks local auth | Keep visible | None |
| Logout | `/logout` | `logout`, `base.html` | Ends local session. | Operators, admins | Required | Required | Protects session boundary | Protects receipt access | Flask session | Operators may stay logged in | Weakens local session control | Keep visible | None |
| Account password change | `/account/change-password` | `account_change_password.html` | Local password maintenance and forced password change flow. | Operators, admins | Required | Required | Protects role identity | Protects resend/config access | `users.py`, session | Password-required users may be stuck | Weakens account lifecycle | Keep visible | None |
| Bootstrap first admin | `/bootstrap/admin` | `bootstrap_admin.html` | First-run admin creation. | Initial admin | Required setup | Required setup | Establishes admin role | Establishes receipt admin support | `users.py` | None after setup | First-run setup blocked | Keep but hide | None |
| Session timeout/lock | `/lock`, shared footer | `_timeout_status.html`, `_timeout_lock_script.html` | Local inactivity lock and action timeout guard. | Operators, admins | Required | Required | Prevents stale commits | Prevents stale resend/config actions | Flask session, templates | Less visible session state | Stale local sessions/actions | Keep visible | None |
| Role enforcement and protected routes | admin guard, auth helpers | `assettrack/auth.py`, `_require_admin_for_route`, tests | Enforces operator/admin boundaries. | All users | Required | Required | Prevents unauthorized custody/admin actions | Restricts resend/config/support tools | `users.py`, route decorators/guards | None | Security boundary broken | Keep visible | None |
| 403/404 safe pages | `/missing`, denied routes | `403.html`, `404.html` | Safe recovery from bad route/permission. | Operators, admins | Helpful | Helpful | Avoids dead ends | Avoids support dead ends | Auth context | Minor | User confusion; role ambiguity | Keep visible | None |
| Dashboard/Home | `/dashboard` | `dashboard.html`, `assettrack/dashboard.py` | Read-only status, Issue/Return launch, custody map, counts. | Operators, admins | Core | Core | Core read-only decision surface | Indirect | Dashboard data queries | Operators lose home base | App becomes harder to operate | Keep visible | Issue 29-x: decide whether Reports or Dashboard owns proof drilldowns |
| Dashboard holders | `/dashboard/holders`, `/dashboard/holders/<id>` | `dashboard_holders.html`, `dashboard_holder_detail.html` | Drilldown for holders with assigned assets. | Operators, admins | Core support | Useful when device has holder | Custody proof/support | Indirect | Dashboard drilldowns | Less proof visibility from dashboard | Removes active custody drilldown | Keep but hide | Issue 29-x: consolidate holder drilldowns with Holders/Reports |
| Dashboard cases | `/dashboard/cases`, `/dashboard/cases/<case>` | `dashboard_cases.html`, `dashboard_case_detail.html` | Case/slot capacity and case-based Issue/Return start. | Operators, admins | Storage logistics | Core for location-assigned network devices | Supports storage-to-custody workflows | Indirect | Slots, queue session | Less storage visibility | Breaks case-based queue workflows | Keep visible or contextual | Issue 29-x: decide if Case Status belongs under Dashboard or Reports |
| Case queue start | `/dashboard/cases/<case>/queue` POST | `dashboard_case_queue_start` | Starts Issue or Return queue from selected case assets without committing. | Operators, admins | Useful | Core | Preserves queue-before-preview seam | Receipt comes after commit | Scan queue/session | Operators must scan manually | Removes efficient case workflow | Keep but hide | Issue 29-x: confirm case-start workflow remains supported |
| Manual Add Assets | `/add-assets`, `/add-assets/review`, `/preview`, `/preview/*` | `index.html`, `preview.html`, intake/preview routes | Direct import/manual staging and generic batch preview. Hidden from normal nav. | Admin/support, direct operator use | Useful for creation/import | Useful for creation/import | Adds assets; legacy Issue mode support | Legacy issue path may create receipt | Scan queue/session, ingest | Low; already hidden | Import/manual add path breaks | Keep but hide | Issue 29-x: recon generic Preview Issue Mode before any removal |
| Asset import | `/` POST upload/intake paths | `app.py:intake`, `assettrack/ingest/*` | CSV/XLSX-style intake and commit of staged assets. | Operators/admins depending setup | Core initial load | Core initial load | Creates asset/event records | No direct receipt unless Issue mode | Ingest parser/committer | Harder to find import | Cannot onboard assets | Keep but hide unless operationally needed | Issue 29-x: decide whether import gets an admin nav entry |
| Network-device CSV import | CLI/script, docs fixtures | `assettrack/network_asset_import.py`, `scripts/import_network_assets_csv.py`, network fixture docs | Custody-only switch/router import; rejects CMDB fields. | Admin/support | Not relevant | Core for switch/router staging | Creates physical custody assets via ingest path | No direct receipt | Existing slots, ingest committer | Hidden CLI may be missed | Network onboarding becomes manual | Keep but hide | Issue 29-x: decide if custody-only network import needs admin UI |
| Network-device staging docs | docs fixture CSV/MD | `docs/fixtures/imports/network/*` | Offline staging contract for switches/routers. | Admin/support | Not relevant | Core planning/support | Preserves custody-only boundary | None | Import script | Operators may not find template | Risk of ad hoc CMDB data | Keep but hide | Issue 29-x: add admin link to template if needed |
| Issue entry/prerequisites | `/issue`, `/issue/location` POST | `return_queue.html` reused, `_workflow_context_banner.html` | Select holder and current location before scanning. | Operators | Core | Required when network device has person custody | Core | Leads to Issue receipt | Holders, buildings, scan queue | Breaks workflow clarity | Breaks required seam | Keep visible | None |
| Issue scan queue | `/issue`, `/` queue POST | `return_queue.html`, `intake` queue logic | Stage assets for Issue before preview. | Operators | Core | Core when person custody applies | Core | Receipt generated after commit | Scan queue/session | Cannot stage reliably | Unsafe direct commit pressure | Keep visible | None |
| Issue preview | `/issue/preview` | `issue_preview.html` | Review holder, current location, assets, blockers, commit acknowledgments. | Operators | Core | Core when person custody applies | Core | Confirms receipt-generating action | Queue, holder, location validation | Cannot safely review | Violates preview-before-commit seam | Keep visible | None |
| Issue commit | `/issue/commit` POST | `issue_commit`, `_issue_batch` | Appends Issue events and creates receipt queue record. | Operators | Core | Core when person custody applies | Core append-only action | Core Issue receipt creation | Events, assets, receipt_queue | N/A workflow endpoint | Issue impossible | Keep visible as workflow action | None |
| Return entry/queue | `/return` | `return_queue.html` | Stage issued assets for Return. | Operators | Core | Core when returning person-custodied device | Core | Leads to Return receipt | Scan queue/session | Cannot return efficiently | Breaks return workflow | Keep visible | None |
| Return preview | `/return/preview` | `return_preview.html` | Review return destination/home slot, blockers, acknowledgments. | Operators | Core | Core when returning person-custodied device | Core | Confirms receipt-generating action | Queue, slots, validation | Cannot safely review | Violates preview-before-commit seam | Keep visible | None |
| Return commit | `/return/commit` POST | `return_commit`, `_return_batch` | Appends Return events and creates receipt queue record. | Operators | Core | Core when applicable | Core append-only action | Core Return receipt creation | Events, assets, receipt_queue | N/A workflow endpoint | Return impossible | Keep visible as workflow action | None |
| Asset search | `/assets/search` | `asset_search.html` | Find assets by tag/serial, inspect current state and last proof. | Operators, admins | Core | Core | Core proof/discovery | Links to movement receipt | Assets, events, receipts | Harder asset lookup | Removes key proof path | Keep visible | Issue 29-x: decide whether primary nav should say Assets instead of Reports |
| Asset detail/history via search | `/assets/search?asset_tag=...` | `asset_search.html`, event/proof query helpers | Current holder/location/status plus last movement proof. | Operators, admins | Core | Core | Core | Receipt proof link | Asset events, receipt_queue | Less visible proof | Audit usability loss | Keep visible/contextual | Issue 29-x: decide if dedicated asset detail/history page is needed |
| Complete asset event history | Event log plus proof/report surfaces | `asset_events` table, `asset_search.html`, `report_readonly.html`, `admin_human_report.html` | Full history is stored append-only; current UI exposes current state, last movement proof, report sections, and recent events rather than a dedicated per-asset timeline. | Operators, admins | Core | Core | Core authoritative record | Receipt links document Issue/Return history | `asset_events`, receipt snapshots | If hidden further, audit confidence drops | Removing event history violates core invariant | Keep visible or improve contextual access | Issue 29-x: decide if a dedicated asset history page is needed |
| Location movement | Issue location context, slot assignment/move, admin asset edit | `issue_location_update`, `admin_assign_slot.html`, `admin_slot_move.html`, `admin_edit_asset.html` | Records or supports where an asset is stored or where custody action occurred. | Operators for Issue context; admins for storage moves | Core | Core | Core location/status context | Receipt snapshots include Issue location context | Buildings, slots, assets/events | Operators/admins may miss location tools | Network-device and storage workflows degrade | Keep visible/contextual | Issue 29-x: define operator-facing location movement boundary |
| Asset status changes | Admin edit, retire, replace, correction routes | `admin_edit_asset.html`, `admin_retire_asset.html`, `admin_replace_asset.html`, `admin_correct_event` | Changes active/terminal/support status through guarded admin tools. | Admin | Support | Core support | Status history/audit | Indirect | Assets/events/audit | Status support less discoverable | Cannot mark retired/failed/replaced assets | Keep but hide/contextual | Issue 29-x: group status-change tools under admin corrections |
| Holder search | `/holders` | `holders_search.html` | Find/select custody holders. | Operators, admins | Core | Useful when device has holder | Core for Issue | Holder email supports receipts | Holders, organizations | Issue holder selection harder | Breaks custody actor selection | Keep visible | None |
| Holder detail | `/holders/<id>` | `holder_detail.html` | Holder identity, assets in custody, follow-up email. | Operators, admins | Core | Useful when device has holder | Core support | Follow-up communication, recipient info | Holders, assets, SMTP | Less custody visibility | Loses holder proof/support | Keep visible/contextual | Issue 29-x: decide whether follow-up stays expanded or secondary |
| Holder create/edit/select/clear | `/holders/new`, `/holders/edit/<id>`, `/holders/select`, `/holders/clear` | holder templates/routes | Manage/select holder reference records for workflows. | Operators, admins | Core | Useful when person custody applies | Core | Holder email feeds receipts | Holders table | Cannot create/select holder | Issue receipts lose recipient source | Keep visible/contextual | None |
| Holder list alias | `/holders/list` | redirects to search | Legacy/all-holders access. | Operators, admins | Support | Support | Support | Indirect | Holder search | None | Low if redirect retained | Keep but hide | Issue 29-x: remove alias only after route-use check |
| Holder follow-up email | `/holders/<id>/follow-up-email` POST | `holder_detail.html`, `_send_holder_followup_email` | Manual reminder that does not record or change custody. | Operators, admins | Useful | Useful when holder exists | Explicitly not custody | Communication support, not receipt | SMTP, holder email | Support action less obvious | Removes follow-up channel | Keep visible or clearly accessible | Issue 29-x: decide if follow-up remains separate workflow |
| Receipt detail/proof | `/receipts/<id>` | `receipt_detail.html` | Immutable receipt proof, delivery status, send/resend actions, PDF. | Operators, admins | Core | Core when custody action occurred | Proof of committed action | Core | receipt_queue, SMTP, recovery mode | Operators lose receipt confirmation | Breaks receipt proof/support | Keep visible/contextual | None |
| Receipt PDF | `/receipts/<id>/pdf` | `_build_receipt_pdf`, `receipt_pdf` | Download deterministic receipt PDF from stored snapshot. | Operators, admins | Core | Core when custody action occurred | Proof artifact | Core | reportlab, receipt snapshot | Less convenient proof | Removes portable receipt proof | Keep visible | None |
| Receipt list/search | `/receipts` | `receipts_list.html` | Search receipts by type/status/holder/location/date. | Operators, admins | Support | Support | Audit/support | Core troubleshooting | receipt_queue | Harder troubleshooting | Removes receipt history search | Keep visible under Reports/support | Issue 29-x: decide whether receipt search is operator nav or support-only |
| Receipt send/retry | `/receipts/<id>/send` POST | `receipt_send` | Send pending or failed receipt email. | Authorized users | Core | Core when custody action occurred | Does not affect custody | Core delivery | SMTP, receipt_queue, recovery mode | Pending email support hidden | Delivery follow-up blocked | Keep visible where authorized | Issue 29-x: confirm operator vs admin send permission posture |
| Receipt resend | `/receipts/<id>/resend` GET/POST | `receipt_resend_get`, `receipt_resend` | Authorized resend of delivered receipt; GET redirects to detail. | Authorized users | Core support | Core support | Does not affect custody | Core delivery support | SMTP, receipt_queue, recovery mode | Support path less obvious | Cannot resend receipt | Keep visible or support/admin accessible | Issue 29-x: decide resend placement |
| Receipt CC settings | `/admin/receipt-cc` | `admin_receipt_cc.html`, `assettrack/settings.py` | Configure local CC delivery metadata. | Admin | Core support | Core support | Not custody truth | Core delivery metadata | app_settings/env fallback | Admins may miss config | CC support removed | Keep visible in Admin Delivery | None |
| Email failure handling | receipt detail/send routes | `receipt_detail.html`, `_update_receipt_delivery_state` helpers | Shows pending/sent/failed and last error without changing custody. | Operators, admins | Core | Core | Protects custody/email boundary | Core | SMTP, receipt_queue | Failure may be missed | Operators may believe custody rolled back | Keep visible | None |
| Operator report | `/report` | `report_readonly.html` | Read-only current system state, drilldowns, receipt search link. | Operators, admins | Core support | Core support | Audit/reconciliation support | Receipt troubleshooting link | Report query helpers | Less audit visibility | Removes operator-safe snapshot | Keep visible | Issue 29-x: decide if Reports remains primary nav |
| Admin report | `/admin/report` | `admin_human_report.html` | Admin read-only operational report with backup/PDF actions. | Admin | Support | Support | Audit/admin support | Indirect | Report query helpers | Admin support path hidden | Removes admin audit overview | Keep visible in Admin | Issue 29-x: consolidate with operator report or keep separate |
| Admin report PDF | `/admin/report/pdf` | `_build_admin_human_report_pdf` | Download human-readable PDF report. | Admin | Support | Support | Audit/export support | Indirect | reportlab | Low | Loses portable admin report | Keep but hide/contextual | Issue 29-x: confirm PDF report operational value |
| DB backup export | `/admin/db/export` | `admin_db_export` | Download raw SQLite backup. | Admin | Core ops | Core ops | Preserves authoritative data | Preserves receipts | SQLite file | Backup less obvious | Recovery readiness loss | Keep visible in Admin | None |
| DB restore | `/admin/db/restore` | `admin_db_restore.html`, `assettrack/restore.py` | Two-phase validate/confirm restore, rollback, recovery mode. | Admin | Core ops | Core ops | Operational recovery, not custody event | Blocks resend until ack | SQLite, restore state/history | Restore support hidden | Disaster recovery loss | Keep visible in Admin | None |
| Recovery mode acknowledgment | `/admin/recovery/acknowledge` POST | `admin_system.html`, restore helpers | Clears active recovery mode after admin review. | Admin | Core ops | Core ops | Protects post-restore review | Unblocks resend/retry | Recovery state | Resend stays blocked | Recovery cannot complete | Keep visible when active | None |
| Admin Tools hub | `/admin/system` | `admin_system.html` | Grouped admin destinations, recovery/system/restore history. | Admin | Core support | Core support | Admin support | Delivery/support tools | Admin guard | Admins hunt through URLs | Admin tools fragmented | Keep visible | None |
| User admin | `/admin/users`, user POST routes | `admin_users.html`, `users.py` | Create users, roles, active state, temp password. | Admin | Core | Core | Role integrity | Restricts receipt support | Users table | User support hidden | Auth lifecycle broken | Keep visible in Admin | None |
| Reference data | `/admin/reference-data` | `admin_reference_data.html`, `reference_data.py` | Organizations, buildings, organization-building mapping. | Admin | Core | Core for locations | Location context | Receipt location context | Reference tables | Location setup harder | Breaks location/reference clarity | Keep visible in Admin | None |
| Holder import | `/admin/holders/import` | `admin_holder_import.html`, `holder_import.py` | CSV import/update of holders by email. | Admin | Useful | Useful when holders apply | Supports custody actor records | Supports recipient email | CSV importer | Bulk holder setup hidden | Manual holder load only | Keep visible in Admin | None |
| Admin asset creation | `/admin/assets/new`, `/admin/assets/create` | `admin_new_asset.html`, `assettrack/assets.py` | Create individual asset records. | Admin | Core | Core | Asset existence/status | No direct receipt | Assets, slots, events | Direct creation hidden | Cannot add single assets | Keep visible via Admin Tools or asset search | Issue 29-x: add Admin Tools link if needed |
| Admin asset edit | `/admin/assets/edit` | `admin_edit_asset.html`, `assettrack/assets.py` | Correct mutable asset metadata/storage relation within rules. | Admin | Core support | Core support | Status/location maintenance | Receipt snapshots not rewritten | Assets, audit/events | Harder support | Cannot correct records | Keep visible/contextual | Issue 29-x: decide Admin Tools placement |
| Admin retire asset | `/admin/assets/retire` | `admin_retire_asset.html` | Terminal status for retired/disposed assets. | Admin | Support | Support | Status event/terminal state | Indirect | Assets/events | Less visible destructive action | Cannot retire assets | Keep but hide/contextual | Issue 29-x: confirm admin correction grouping |
| Admin replace asset | `/admin/assets/replace` | `admin_replace_asset.html` | Replace failed asset with guarded event/state updates. | Admin | Support | Support, especially network devices | Status/location maintenance | Indirect | Assets, slots/events | Less visible support action | Cannot handle failed equipment cleanly | Keep but hide/contextual | Issue 29-x: confirm replacement remains in barebones |
| Event correction | `/admin/events/correct` POST | `admin_correct_event` | Amend-only event correction support. | Admin | Audit support | Audit support | High custody/audit relevance | Indirect | asset_events correction model | Hidden by design acceptable | Audit correction impossible | Keep but hide | Issue 29-x: document/admin surface for correction workflow |
| Slot provision | `/admin/slots/provision` | `admin_slot_provision.html` | Create empty storage slots/case capacity. | Admin | Core for case storage | Core for network-device locations | Storage logistics | Indirect | Slots | Storage setup harder | Cannot model case slots | Keep visible in Admin Storage | None |
| Assign slot | `/admin/assign-slot` | `admin_assign_slot.html` | Assign unslotted asset to storage slot. | Admin | Core support | Core for location-assigned devices | Storage logistics | Indirect | Slots, assets | Unslotted cleanup harder | Storage state remains incomplete | Keep visible in Admin Storage | None |
| Slot move | `/admin/slot-move` | `admin_slot_move.html` | Move storage asset to another slot. | Admin | Support | Core support for network-device storage | Location movement | Indirect | Slots, assets/events | Hidden support action | Cannot record physical moves | Keep but hide/contextual | Issue 29-x: decide if location movement needs operator surface |
| Force vacate slot | `/admin/force-vacate` | `admin_force_vacate.html` | High-risk administrative slot correction. | Admin | Support | Support | Storage correction | None | Slots, assets/events | Good to hide from casual use | Cannot recover inconsistent slot occupancy | Keep but hide | Issue 29-x: keep as emergency admin tool |
| Public demo page | `/demo`, `/demo/send-sample-receipt` | `demo.html`, demo helpers | Public sample with static/demo-only receipt send. | Public/support | Marketing/support only | Marketing/support only | No custody writes | Demo receipt only | SMTP, token env | No core impact | Product demo removed | Candidate for later removal from barebones core | Issue 29-x: decide if public demo remains product surface |
| Static assets/theme | `/static/*`, base theme toggle | CSS/images/base template | Local UI styling and light/dark toggle. | All | Usability | Usability | Indirect | Indirect | Local static files/cookie | Lower usability | UI degrades | Keep visible | None |

## Email Receipt Boundary

Email receipts are core. They must not be removal candidates.

| Capability | Current behavior | Barebones classification | Boundary |
|---|---|---|---|
| Automatic Issue receipt generation | `issue_commit` appends events, inserts an ISSUE row in `receipt_queue`, then redirects to receipt detail. | Keep visible | Receipt documents committed custody; it does not create custody. |
| Automatic Return receipt generation | `return_commit` appends events, inserts a RETURN row in `receipt_queue`, then redirects to receipt detail. | Keep visible | Receipt documents committed return; it does not reverse custody. |
| Recipient selection | Recipient comes from the holder snapshot/email associated with the committed batch. | Keep visible through holder workflows | Holder email is delivery metadata for receipts, not custody truth. |
| CC configuration | Admin-only `/admin/receipt-cc`; local `app_settings` with env fallback. | Keep visible in Admin Delivery | CC is delivery metadata only. |
| Delivery status | Receipt detail/list show pending, sent, failed, attempts/errors. | Keep visible where operators confirm completion | Delivery state must not affect custody state. |
| Email delivery failures | Failures are surfaced on receipt detail and stored as delivery status/error. | Keep visible | Failure must not roll back events or receipts. |
| Authorized send/retry/resend | Receipt detail POST actions send pending/failed/delivered receipts when allowed; recovery mode blocks resend/retry. | Keep visible or clearly support-accessible | Sending changes delivery metadata only. |
| Direct resend route behavior | GET `/receipts/<id>/resend` redirects to detail; POST performs resend. | Keep but hide direct GET | Prevents duplicate navigation while preserving action. |
| Receipt proof visibility | Receipt detail and PDF show stored snapshot facts, assets, holder, location, acknowledgments. | Keep visible | Proof is based on stored receipt/event facts. |
| Receipt history | `/receipts` search and report links expose receipt history. | Keep visible under Reports/support | Supports audit and troubleshooting. |
| Holder follow-up communication | Manual holder email on holder detail. | Keep visible or secondary | It is a reminder only, not receipt/custody proof. |
| Role restrictions | CC/admin tools are admin-only; receipt access/actions are protected authenticated routes. | Keep visible by role | Do not weaken route protection. |

## Minimum Laptop Workflow

Barebones operator flow for a laptop:

1. Find the laptop in `/assets/search` or from Dashboard/Reports.
2. Review current state: holder, location type, home case/slot, status cue, and last movement proof.
3. Open `/holders` and select the receiving holder, creating/editing the holder if needed.
4. Open `/issue`; confirm holder and current building/room.
5. Scan/add the laptop to the Issue queue.
6. Open `/issue/preview`; review holder, current location, assets, blocked items, and commit acknowledgment.
7. POST `/issue/commit`; events are appended and an ISSUE receipt is created.
8. Review `/receipts/<id>` for proof and delivery status.
9. Send/retry/resend receipt when authorized; confirm pending/sent/failed state.
10. For return, open `/return`, scan the laptop, review `/return/preview`, and POST `/return/commit`.
11. Review the RETURN receipt and delivery status.
12. Use `/assets/search`, `/report`, receipt detail/PDF, and holder detail for complete operational history/proof.

Pages that support this workflow: Dashboard, Asset Search, Holders, Holder Detail, Issue queue, Issue Preview, Receipt Detail/List/PDF, Return queue, Return Preview, Reports.

Pages that can create unnecessary operator load if surfaced too broadly: generic `/preview` Issue Mode, dashboard case starts for non-case work, receipt list when the operator only needs the just-created receipt, admin correction tools, public demo.

## Minimum Network-Device Workflow

Barebones operator/admin flow for a switch or router:

1. Find the device in `/assets/search`, `/report`, Dashboard custody map, or case/slot drilldowns.
2. Review current location type, building/case/slot, status, and last movement proof.
3. If onboarding many switches/routers, use the custody-only network staging CSV and `assettrack/network_asset_import.py`; do not add CMDB fields.
4. If onboarding one device, use admin asset creation and slot assignment.
5. Assign or move the device to a location using existing storage slot tools or approved asset/location admin tools.
6. Change operational/terminal status through admin asset edit, retire, replace, or correction tools when authorized.
7. Record a person-based Issue or Return only when the device is actually issued to or returned from a holder.
8. Generate and deliver email receipts for those custody actions only.
9. View complete proof through asset search, reports, receipt detail/PDF, and event/proof links.

Network devices remain part of the same asset system. A network device may be location-assigned and have no holder. AssetTrack should continue to reject CMDB/network configuration fields such as IP address, MAC address, VLAN, topology, switch port, patching, and running configuration.

## Proposed Barebones Operator Navigation

| Navigation item | Why necessary | Keep visible? |
|---|---|---|
| Dashboard or Home | Starting point for current state, Issue, Return, and high-level custody/storage visibility. | Yes |
| Issue | Core custody workflow for person-assigned assets and applicable network devices. | Yes |
| Return | Core custody workflow for returning person-assigned assets. | Yes |
| Assets or Asset Search | Fast lookup by tag/serial and proof access. Current app exposes this under Dashboard/Reports links, but barebones navigation should consider making it explicit. | Yes or visible under Reports pending Greg decision |
| Holders or Holder Search | Required to select custody actor and inspect assets held. | Yes |
| Reports / History / Proof | Read-only custody state, receipt search, asset/holder/case drilldowns. | Yes, but may be renamed or narrowed |
| Receipt delivery/resend access | Operators need confirmation after Issue/Return and authorized recovery from failed sends. | Contextual from receipt detail; primary nav not required |

The workflow seam must stay intact: entry page, prerequisite selection, scan queue, preview, commit, receipt confirmation. Navigation may reduce choices, but must not skip preview or hide commit consequences.

## Proposed Barebones Administrator Navigation

| Navigation item | Why necessary | Keep visible? |
|---|---|---|
| All operator capabilities | Admins must be able to verify and support live workflows. | Yes |
| Admin Tools | Scan-friendly hub for protected admin actions and recovery state. | Yes |
| Users | Local auth, roles, active state, temporary passwords. | Yes |
| Reference Data | Organizations, buildings, mappings used by location and holder workflows. | Yes |
| Import Holders | Bulk setup for custody actors and receipt recipient emails. | Yes |
| Assets / Create / Edit | Add single assets and correct asset metadata/state within approved rules. Current visibility is contextual; consider admin hub placement. | Yes or contextual pending Greg decision |
| Storage tools | Empty slots, assign slot, slot move, force vacate. Required for location-assigned devices and storage reconciliation. | Yes, with high-risk tools contextual/hidden |
| Receipt and Email Configuration | Receipt CC and delivery support. | Yes |
| Receipt Support Tools | Receipt search/detail/PDF/send/resend/failure review. | Yes, under Reports or Admin Delivery |
| Backup | Raw SQLite backup is core operational support. | Yes |
| Restore / Recovery | Guarded restore, recovery mode, history, acknowledgment. | Yes |
| Administrative corrections | Retire, replace, event correction, force vacate. | Keep but hide/contextual |

## Reporting And Export Review

| Report or export | Route/location | Supports active custody | Supports audit verification | Supports reconciliation | Supports email troubleshooting | Laptop tracking | Network-device tracking | Duplicate risk | Classification | Future issue |
|---|---|---|---|---|---|---|---|---|---|---|
| Operator current state report | `/report` | Yes | Yes | Yes | Links to receipts | Yes | Yes | Some overlap with Dashboard and Asset Search | Keep visible | Issue 29-x: decide report scope/name |
| Receipt search/list | `/receipts` | After commit/support | Yes | Partial | Yes | Yes | Yes | Overlaps receipt detail when opened from commit | Keep visible under Reports/support | Issue 29-x: simplify duplicate receipt navigation |
| Receipt detail | `/receipts/<id>` | Yes after commit | Yes | Yes for movement proof | Yes | Yes | Yes | None; this is proof surface | Keep visible | None |
| Receipt PDF | `/receipts/<id>/pdf` | Support | Yes | Yes | Communication artifact | Yes | Yes | Duplicates detail in portable form | Keep visible | None |
| Asset search proof | `/assets/search` | Yes | Yes | Yes | Links receipt proof | Yes | Yes | Overlaps report drilldown | Keep visible | Issue 29-x: decide if explicit primary nav |
| Dashboard holder drilldowns | `/dashboard/holders*` | Yes | Partial | Yes | No | Yes | When holder applies | Overlaps Holders/Report | Keep but hide/contextual | Issue 29-x: consolidate drilldowns |
| Dashboard case drilldowns | `/dashboard/cases*` | Yes | Partial | Yes | No | Yes | Yes | Overlaps report/case status | Keep visible/contextual | Issue 29-x: decide nav ownership |
| Admin human report | `/admin/report` | Support | Yes | Yes | Indirect | Yes | Yes | Overlaps operator report | Keep visible in Admin | Issue 29-x: compare admin/operator report value |
| Admin report PDF | `/admin/report/pdf` | Support | Yes | Yes | No | Yes | Yes | Portable duplicate of admin report | Keep but hide/contextual | Issue 29-x: confirm PDF demand |
| SQLite backup export | `/admin/db/export` | Operational recovery | Authoritative backup | Full data preservation | Preserves receipt data | Yes | Yes | Not duplicate; raw backup | Keep visible in Admin | None |
| Restore history/recovery state | `/admin/system`, restore files | No direct custody work | Operational audit | Recovery verification | Controls resend blocking | Yes | Yes | No | Keep visible to admins | None |
| Demo sample receipt | `/demo` | No | No | No | Demonstrates only | No real data | No real data | Product/demo duplicate | Candidate for later removal from core | Issue 29-x: decide demo product boundary |
| Network staging template | docs fixture | Onboarding support | Input control | Import validation | No | No | Yes | Not a report; staging artifact | Keep but hide | Issue 29-x: decide admin discoverability |

## Recommended Future Simplification Map

Do not implement these in Issue 29-1. They are candidate issue cards only.

| Candidate issue | Scope | Why it matters |
|---|---|---|
| Issue 29-x: Rename or expose Asset Search in primary navigation | Decide whether Reports remains the route to asset proof or whether Assets deserves a primary nav item. | Operators must find assets quickly under pressure. |
| Issue 29-x: Decide report/navigation ownership | Decide Dashboard vs Reports vs Asset Search ownership for current custody, cases, holders, and proof. | Reduces duplicate choices without hiding proof. |
| Issue 29-x: Receipt support placement | Decide whether resend/search stays operator-visible, admin-visible, or contextual only. | Keeps delivery recovery accessible without overloading primary nav. |
| Issue 29-x: Generic Preview Issue Mode recon | Determine whether generic `/preview` Issue Mode is still active, redundant, or removable. | Avoids removing a hidden workflow dependency. |
| Issue 29-x: Network import discoverability | Decide whether CLI network import should get an admin UI/link or remain support-only. | Network devices are core, but CMDB scope must stay out. |
| Issue 29-x: Admin asset tools grouping | Decide whether create/edit/retire/replace should appear in Admin Tools or stay contextual. | Admins need asset support without exposing high-risk tools casually. |
| Issue 29-x: Demo boundary decision | Decide whether `/demo` remains part of product, sales/support only, or removable. | Public demo is not required for offline field operation. |
| Issue 29-x: Holder follow-up placement | Decide whether manual follow-up remains on holder detail or moves to receipt/support context. | Avoids confusing reminders with custody receipts. |

## Open decisions requiring Greg’s approval

- Whether Reports remains in primary operator navigation or is renamed/split into Assets, History, and Receipts.
- Whether reconciliation/case status remains operator-facing from Dashboard, Reports, or both.
- Whether authorized receipt resend belongs to operators, administrators, or both.
- Whether holder follow-up remains a separate workflow or becomes a secondary support action.
- Whether public demo pages remain part of the product boundary.
- Whether custody-only network-device staging/import remains CLI/support-only or becomes admin-visible.
- Whether admin asset creation/edit/retire/replace should be promoted in Admin Tools.
- Whether slot movement and force-vacate remain hidden support tools or get clearer admin grouping.
- Whether admin and operator reports should be consolidated.
- Whether any report/export is low-value enough for future removal.
- Whether a dedicated asset detail/history page is needed beyond current Asset Search proof rows.
- Whether future schema changes are ever needed for location movement, receipt delivery history, or network-device status detail.
- Whether any candidate removal would require security, persistence, schema, event, or email behavior approval before implementation.

## Non-Negotiable Implementation Guardrails For Future Issues

- Do not change event history semantics to simplify screens.
- Do not make email delivery custody truth.
- Do not remove receipt generation, Issue delivery, Return delivery, delivery status, or authorized resend.
- Do not remove backup, restore, or recovery.
- Do not hide protected admin tools so deeply that recovery or role maintenance is unavailable.
- Do not split network devices into a separate custody application.
- Do not add CMDB/network configuration tracking to make network devices feel complete.
- Do not shortcut entry -> prerequisite -> queue -> preview -> commit.
