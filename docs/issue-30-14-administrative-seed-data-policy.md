# Issue 30-14 Administrative Seed-Data Policy

Classification: Class 2 - Logic / Behavior policy. This document is policy and reconnaissance only; it does not change runtime behavior.

Why it matters: asset creation and import depend on reference data, storage capacity, and holder records. Those prerequisites must be explicit so future import work does not silently invent custody, location, or schema truth.

## Current Repository Behavior

| Category | Current source of truth | Required before first asset? | Current creation method | Current normalization and collisions | Current audit/event coverage |
| --- | --- | --- | --- | --- | --- |
| Asset types | `assettrack/assets.py:APPROVED_NEW_EQUIPMENT_TYPES`, `validate_new_equipment_type`; UI defaults in `assettrack/intake/app.py` | Yes. New assets must be `laptop`, `switch`, or `router`. | System-provided enum in code. No admin UI for new types. | Trim/lowercase; unsupported new types rejected. Legacy labels can display but cannot be used for new asset creation. | Asset creation events include equipment type when the creating path records it. |
| Organizations | `assettrack/db.py` schema and Ad Hoc bootstrap; `assettrack/reference_data.py:create_organization`; `assettrack/holder_import.py:_ensure_organization` | No for asset creation. Yes for holder creation/import. | Bootstrap/migration creates `Ad Hoc`; admin UI creates named organizations; holder CSV import creates missing organizations. | Trimmed name; case-insensitive unique table constraint and helper checks. | No asset event. Tests confirm reference changes do not rewrite asset events or receipt snapshots. |
| Buildings | `assettrack/reference_data.py:create_building`, `update_building_name`, `set_building_active` | No for current asset creation; needed for operator issue-location choices and org-building mapping. | Admin reference-data UI only. | Trimmed name; case-insensitive unique table constraint and helper checks; active/inactive flag. | No asset event. Tests confirm corrections/deactivation do not rewrite asset events or receipt snapshots. |
| Rooms | Asset fields and workflow form values; no `rooms` table found. | No for current individual asset creation. No repository-level room seed table exists. | Entered as form/import text; unsupported as independent direct seed data. | Trimmed text in UI; not globally unique or centrally validated. | Room appears in asset creation, slot assignment, issue events, and receipt snapshots when those paths include it. |
| Cases | `slots.case_name`; dashboard/report code derives cases from slots. | Required only for slotted asset creation/import. | Admin slot provisioning creates slots for a case; XLSX importer can create case slots from workbook rows; network import requires existing slots when assignment is requested. | UI uppercases case numbers; slot table enforces unique `(case_name, slot_position)`. | Empty case/slot provisioning has no asset event. Slot assignment with an asset appends events in current asset/import paths. |
| Slots | `assettrack/intake/app.py:admin_slot_provision`, `_resolve_slot_selection`; `assettrack/slots.py`; `scripts/import_inventory.py` | Required before slotted asset creation except the current documented XLSX import currently creates slots itself. Not required for unslotted asset creation. | Admin UI provisions empty slots; XLSX importer creates slots; network import and admin new asset select existing slots. | Case uppercased in UI/imports; slot count/position parsed as integer; occupied slots rejected by current create/import paths. | Empty slot provisioning has no audit event; asset-slot assignment appends `SLOT_ASSIGN` in admin new asset and current documented XLSX import, and via generic committer for ingest paths. |
| Holders | `assettrack/holders.py:create_holder`, `update_holder`; `assettrack/holder_import.py:import_holders_csv` | No for first asset. Yes before Issue custody workflows. | Admin holder UI and holder CSV import. | Name trimmed; email normalized lowercase and unique by helper/import logic; organization required by current holder helpers. | Holder create/import/update does not append asset events. Custody events reference holder when assets are issued/returned. |
| Organization-building mappings | `assettrack/reference_data.py:create_organization_building_mapping` | No for first asset. Needed for controlled issue-location choices by organization. | Admin reference-data UI. | Unique `(organization_id, building_id)`; inactive buildings rejected. | No asset event; no receipt/event rewrite. |

## Proposed Target Policy

### First Asset Prerequisites

Before the first asset can be created or imported, AssetTrack must have:

- An initialized SQLite schema from the current bootstrap/startup path.
- An authenticated admin for UI creation paths, or a documented local CLI/import operating path where the relevant issue has defined support status.
- A system-provided equipment type: Laptop, Switch, or Router.
- A unique asset tag.
- For UI single-asset creation: serial number, manufacturer, and optional building text, room text, model/model code/notes.
- For slotted creation/import: an empty storage slot, unless the relevant import issue explicitly defines that path as the owner of slot creation.

Not required before the first asset:

- Holder records, unless the next action is Issue custody.
- Organization records beyond the system-provided `Ad Hoc`, unless creating/importing holders or organization-building mappings.
- Building reference rows, unless the workflow needs controlled building selection for Issue location.

### Required, Optional, Admin-Created, System-Provided

| Data | Policy class | Creation method | Direct DB editing |
| --- | --- | --- | --- |
| SQLite schema | Required system foundation | Startup/bootstrap/migration only | Unsupported |
| Asset types | Required for new assets; system-provided | Code-defined allowlist only | Unsupported |
| Asset tag | Required per asset | UI or import path whose support status is defined by its owning issue | Unsupported |
| Serial number | Required by current admin new asset; optional in some imports | UI or import path whose support status is defined by its owning issue | Unsupported |
| Manufacturer | Required by current admin new asset; optional in some imports | UI or import path whose support status is defined by its owning issue | Unsupported |
| Building text | Optional in current individual asset creation and some imports | UI/import field; reference building UI for controlled lists | Unsupported |
| Room text | Optional in current individual asset creation and some imports | UI/import field only; no room seed table | Unsupported |
| Organizations | Required for holders | Bootstrap creates `Ad Hoc`; admin UI; holder import may create missing organizations | Unsupported |
| Buildings | Required for building mappings and controlled Issue location choices | Admin reference-data UI | Unsupported |
| Organization-building mappings | Optional until Issue location needs them | Admin reference-data UI | Unsupported |
| Cases and empty slots | Required for slotted storage | Admin slot provisioning; current documented XLSX import creates slots as part of import pending Issue 30-15 classification | Unsupported |
| Holders | Required for Issue custody | Admin holder UI or holder import whose support status is defined by Issue 30-13 | Unsupported |

### Automatic Creation Rules

AssetTrack may automatically create:

- The SQLite schema through the current startup/bootstrap path.
- The `Ad Hoc` organization during schema/bootstrap compatibility handling.
- Missing organizations during the current holder CSV import, because the import reports created/updated counts and uses organization as holder reference data. Issue 30-13 owns the final holder-import support policy.
- Case/slot rows only in an inventory import whose owning issue explicitly documents slot creation and reports import counts. Issue 30-15 owns the current XLSX and legacy import-tool classification.
- Asset events during asset creation, slot assignment, issue, return, update, and retirement paths.

AssetTrack must never silently create:

- Holders during asset creation or import.
- Custody assignments during asset seed/import.
- Buildings or rooms from arbitrary asset/import text without explicit approval.
- Organization-building mappings from holder or asset imports.
- Slots from network CSV import or generic manual Add Assets unless that path explicitly becomes the owner through a scoped decision with explicit approval.
- New asset types from imported values.
- Audit/event records after the fact to cover old writes.

### Storage Prerequisites

Slotted asset creation/import:

- Requires case and slot as a paired selection/value.
- Requires the target slot to exist and be empty, unless using an import path whose owning issue explicitly defines that path as the owner of slot creation.
- Must reject stale, missing, mismatched, non-numeric, or occupied slot references before commit.
- Must write asset state and slot occupancy in one transaction and append slot assignment evidence when an asset is assigned.

Unslotted asset creation/import:

- May create an asset in storage without `home_slot_id` when the creating path explicitly allows unslotted assets.
- Must not create a placeholder case, slot, room, holder, or custody assignment to satisfy missing storage data.
- Should be visible in reports/dashboard as unslotted until an admin assigns a slot.

### Duplicate, Normalization, Collision, Reuse, Preview, Confirmation

- Normalize asset tags by trimming and uppercasing at input boundaries.
- Reject duplicate asset tags before commit where the path can check them; never merge assets by tag.
- Treat serial-number uniqueness as a collision guard for current admin asset creation and network import. Whether it becomes a universal import rule remains unresolved for Greg.
- Normalize organization and building names by trimming and comparing case-insensitively.
- Reuse existing organizations by case-insensitive name; do not create near-duplicates that differ only by case.
- Reuse existing slots only when the same `(case_name, slot_position)` exists and is empty for assignment.
- Reject duplicate holder emails after lowercasing and trimming; do not choose among multiple existing holders with the same email.
- Every bulk seed/import path should provide either an interactive preview or a validation report before writes. Current paths that only provide stop-on-error behavior should be updated in future issues, not changed here.
- UI seed-data writes must require admin role and deliberate form submission. CLI seed/import writes require an explicit documented local operating boundary because Flask role enforcement does not apply.

## Current Audit Coverage

Current coverage:

- Admin new asset creation appends `ASSET_CREATED` and, when slotted, `SLOT_ASSIGN` in `assettrack/intake/app.py:_create_admin_asset_in_tx`.
- Generic Add Assets and the current network CSV importer use `assettrack/ingest/committer.py:commit_batch`, which appends creation/update-style events and optional slot assignment events.
- The current documented XLSX inventory import appends `ASSET_CREATED` and `SLOT_ASSIGN` in `scripts/import_inventory.py:run_import`.
- Building corrections and deactivation do not rewrite existing asset events or receipt snapshots, covered by `tests/test_admin_reference_data.py`.

Current gaps:

- Organization, building, mapping, empty slot provisioning, and holder import create/update reference rows without a dedicated reference-data audit event.
- CLI imports record string actors, not necessarily app user ids.
- Some reference-data changes are operationally important but not represented in `asset_events`, which is appropriate for asset history but leaves admin seed-data auditing incomplete.

Future audit expectations:

- Add a separate reference-data audit mechanism only with explicit approval if schema or persistence changes are required.
- Do not backfill or mutate existing `asset_events` for past seed-data actions.
- Keep asset custody events append-only and separate from reference-data administration.

## Empty Deployment First-Run Sequence

Minimum useful path for an unslotted first asset:

1. Initialize AssetTrack through the current startup/bootstrap path so the SQLite schema exists.
2. Bootstrap the first admin user.
3. Confirm system defaults are present, including the system-provided asset types and the `Ad Hoc` organization.
4. Create or import an unslotted asset through a path whose owning issue allows unslotted asset creation/import.
5. Provide the current required free-text asset fields for that path, such as asset tag, equipment type, serial number, and manufacturer. Building text and room text are optional for individual asset creation and should be supplied only when they are known.

Reference-data setup is conditional, not mandatory before the first asset:

- Prepare cases and slots only when creating or importing slotted assets.
- Prepare organizations, buildings, organization-building mappings, and holders only when preparing Issue custody, holder import, or controlled location choices.
- Keep free-text asset fields distinct from reference-data prerequisites. Individual asset creation may record building or room text when supplied, but it must not require a building reference row, room table, holder, case, or slot.
- Use Issue/Return workflows only after the relevant holder, location context, and asset records exist.

## Constraints On Milestone 30 Issues

- Issue 30-1 must not introduce automatic holder, building, room, case, slot, or asset-type creation without explicit approval.
- Issue 30-2 owns unslotted asset creation behavior and must preserve the minimum first-asset path without requiring holders, org-building mappings, cases, or slots.
- Issue 30-4 owns removal of unnecessary mandatory Room requirements and must keep current free-text room behavior distinct from any future managed room reference model.
- Issue 30-5 must preserve first-asset prerequisites, reject silent reference-data creation, and keep slotted vs unslotted asset rules explicit.
- Issue 30-6 owns unslotted import behavior and must not add hidden storage, holder, building, room, mapping, case, or slot creation.
- Issue 30-7 adds Import Assets to Admin Tools and must expose only paths whose support status is defined by their owning issues, without hidden reference-data creation.
- Issue 30-11 must either document the ingest CLI as a local admin operating path with validation/report expectations or narrow it to an internal helper.
- Issue 30-12 will decide the canonical Switch/Router import interface and ownership. Any resulting workflow must follow this seed-data policy and must not silently create buildings, rooms, organization-building mappings, holders, or slots without explicit approval.
- Issue 30-13 may allow holder import to create organizations, but must report that behavior and must not create holders from asset imports.
- Issue 30-15 audits unsupported and legacy import tools, including direct-state-write risks and the support classification of older utilities.
- Issue 30-16 turns the conditional first-run sequence into operator-facing deployment guidance.

## Future Implementation Work

- Add or standardize preview/report terminology across admin seed-data and import routes.
- Decide whether serial number uniqueness should be universal for all asset imports.
- Decide whether CLI imports require app-user attribution or a separately defined operator string policy.
- Decide whether reference-data changes need a separate append-only admin audit log. This likely requires Greg approval if it changes schema or persistence.
- Decide whether rooms should stay free text or become managed reference data. A managed room model would require explicit schema approval.
- Align Issue 30-9 follow-on docs with this policy if their current recommendations conflict with the proposed target policy above.

## Decisions Still Requiring Greg Approval

- Any schema or migration for reference-data audit, rooms, serial uniqueness, or import metadata.
- Any change that makes a CLI path supported or unsupported operationally.
- Any change that allows imports to auto-create buildings, rooms, holders, organization-building mappings, or slots outside paths Greg explicitly approves.
- Any retirement of an existing script or route.
