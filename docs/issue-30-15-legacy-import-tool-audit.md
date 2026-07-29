# Issue 30-15 Legacy Import Tool Audit

Classification: Class 2 - Logic / Behavior policy.

Scope: documentation and repository investigation only. No Python, templates, tests, schema, migrations, authentication, Docker, persistence, dependency, runtime behavior, script removal, warning, rename, or relocation was changed.

Why it matters: AssetTrack has several ways to create assets, holders, reference data, slots, or inventory state. Each path needs a clear support boundary so operators do not accidentally bypass Flask roles, preview, event behavior, rollback, attribution, or custody reconciliation.

## Preserved Decisions

- `assettrack.ingest` is an approved internal utility, not an operator-facing interface.
- Issue 30-5 owns inventory import repair, scaling, and deterministic reconciliation.
- Issue 30-12 decides the canonical Switch and Router import interface.
- Issue 30-13 owns Holder import preview and audit policy.
- Issue 30-16 owns operator-facing first-run deployment guidance.
- This audit does not pre-decide implementation details owned by those issues.

## Classification Summary

| Path | Recommendation | Why |
| --- | --- | --- |
| Generic Add Assets UI workflow | Supported operational workflow | Admin-gated staged UI with queue, validation preview, confirmed commit, shared committer, append-only asset events, and queue clearing. |
| Generic `assettrack.ingest` CLI | Internal utility | Approved internal commit adapter, but no Flask role gate, no enforced parser/validator, no preview command, free-text actor, and no direct CLI tests. |
| Network Switch/Router CSV CLI | Internal legacy utility | Domain-specific CSV validation and shared committer for physical Switch/Router asset records. It bypasses Flask roles and has no admin upload, preview, confirmation, or results workflow, so it is not the normal operator procedure. |
| Network import admin template page | Deprecated operator guidance page | Admin-gated guidance/template download only; it performs no upload, validation, preview, transaction, or DB write. Import Assets is the canonical operator workflow. |
| Holder CSV import UI | Supported operational workflow | Admin-gated CSV UI with preview, confirmation, transaction boundary, and persistent append-only Import History for successful admin UI imports. It writes holder/org reference state but does not bypass event-derived asset custody state. |
| Holder CSV import CLI | Internal utility | Same CSV holder importer as UI but no Flask role boundary and no persistent Import History audit row. Useful for local/admin support only unless Issue 30-13 approves more. |
| Admin reference-data UI | Supported operational workflow | Admin-gated creation/update of organizations, buildings, and mappings with helper validation. No asset events, because this is reference data. |
| Admin slot provisioning UI | Supported operational workflow | Admin-gated empty slot seed path with explicit transaction and rollback. No asset/custody event because no asset is assigned. |
| `assettrack.slots.initialize_case_slots` | Internal utility | Helper can seed an entire new case but is not wired to a route or documented operator command. |
| Standard XLSX inventory importer | Fixed-workbook/bootstrap path | Documented Docker path for `data/import/BQ26_ETP.xlsx` with tests and event/state reconciliation, but it writes assets, slots, and occupancy directly outside the shared committer. Normal CSV/XLSX asset imports use Admin Tools -> Import Assets. Issue 30-5 remains the owner for repair and deterministic reconciliation. |
| `scripts/import_inventory_docker.sh` | Fixed-workbook/bootstrap wrapper | Wrapper for the fixed-workbook XLSX importer in the app container. |
| Older BQ26 direct importer | Retire | Legacy direct-state writer with no events, no slot occupancy, no preview, no role gate, no tests, and no supported docs. |
| Root BQ26 CSV/XLSX files | Legacy | Historical source artifacts in the repo root; not the current documented `data/import/BQ26_ETP.xlsx` input path. |
| `legacy/inventory_legacy.db` | Legacy | Inert historical SQLite reference artifact with a non-current schema, explicitly not used by current AssetTrack. Deletion/removal requires Greg's approval. |
| `scripts/validate_fixture.py` and `docs/fixtures/sample_batch.csv` | Internal utility | Parser/validator smoke helper only; does not write and is not wired to CLI commit. |
| Network import fixtures | Internal utility | Template/sample artifacts supporting the network CSV process; do not write. |
| `tools/verify_import.py` | Internal utility | Read-only direct SQLite verification helper for imported state; no Flask role gate but no writes. |
| `assettrack.db init` CLI | Internal utility | Schema/bootstrap utility, not an asset import path; can create default reference foundation. |
| `assettrack.db reset` CLI | Retire | Must not be used against an operational DB; it can delete append-only event history and derived operational state. Quarantine/removal requires a separate approved implementation issue. |

## Detailed Audit

### Generic Add Assets UI Workflow

- Name and location: direct manual Add Assets queue at `GET /add-assets`, shared `POST /`, `POST /add-assets/review`, `GET /preview`, `GET /preview/validate`, and `POST /preview/commit`; implemented in `assettrack/intake/app.py`, `assettrack/intake/to_ingest.py`, `assettrack/ingest/validator.py`, and `assettrack/ingest/committer.py`.
- Invocation method: authenticated browser workflow by direct URL; manual Add Assets launchers remain hidden from normal navigation.
- Purpose: staged asset intake for Laptop, Switch, and Router assets.
- Input format: scanned/entered asset tags plus selected equipment type; optional existing case/slot selection.
- Validation and preview: queue duplicate checks, scan sanitization, slot resolution, `validate_rows`, preview page, and explicit reviewed confirmation before commit.
- Transaction behavior: `commit_batch` writes all rows in one SQLite transaction and rolls back on exception.
- Event and audit behavior: creates asset state through shared helpers and appends `created`, optional `SLOT_ASSIGN`, and `SCAN` events.
- Authentication or role boundary: `GET /add-assets` requires login; review and commit require admin role.
- Actor attribution: ingest rows carry operator data from the adapter/session path; committer records row actor where supplied and helper-created asset events may record `system`.
- Direct derived-state writes: yes, via shared committer and asset helpers; storage state and optional slot occupancy are updated with events in the same transaction.
- Tests and operator documentation: `tests/test_admin_add_asset_ui.py`, `tests/test_basic_auth_guard.py`, `tests/test_issue_23_2_preview_commit_seam.py`, `tests/test_issue_clear_queue.py`, and related UI tests. Direct URL remains intentionally available under AGENTS.md.
- Relationship to current workflows: supported operational workflow. Issue 30-5 owns repair/scaling/reconciliation for inventory import and must not be pre-decided here.

### Generic `assettrack.ingest` CLI

- Name and location: `assettrack/ingest/cli.py`, invoking `assettrack.ingest commit`.
- Invocation method: local CLI, `commit --db <sqlite-path> --rows-json <json-file>`.
- Purpose: commit already-shaped ingest rows through `commit_batch`.
- Input format: JSON list of committer rows, either flat dict rows or `{row_number, data}` objects.
- Validation and preview: none enforced by CLI. Parser and validator exist elsewhere, and the help text says "validated preview rows", but `main()` only loads JSON and calls `commit_batch`.
- Transaction behavior: shared `commit_batch` all-or-nothing SQLite transaction.
- Event and audit behavior: appends asset events through the committer, including `SCAN`, `ISSUE`, `RETURN`, `UPDATE`, or `RETIRE`. Generic ISSUE/RETURN rows do not pass through dedicated custody receipt/prerequisite workflows.
- Authentication or role boundary: bypasses Flask login, session timeout, and role checks.
- Actor attribution: free-form row `operator_id`; not linked to an app user. New-asset helper events may use actor `system`.
- Direct derived-state writes: yes, through the committer; can mutate asset and slot state.
- Tests and operator documentation: no direct CLI test or operator-facing documentation found; committer behavior is exercised indirectly.
- Relationship to current workflows: approved internal utility only. It should not be exposed as an operator-facing path without a separate approved implementation issue.

### Network Switch/Router CSV CLI

- Name and location: `assettrack/network_asset_import.py` with wrapper `scripts/import_network_assets_csv.py`.
- Invocation method: local CLI, `python scripts/import_network_assets_csv.py <csv> --db data/assettrack.db --actor <actor>`.
- Purpose: physical Switch and Router inventory or asset-record import; intentionally not a CMDB or network-configuration import.
- Input format: CSV with allowed columns including `asset_tag`, `barcode`, `serial_number`, `equipment_type`, `manufacturer`, `model`, `location_building`, `case_identifier`, `slot_identifier`, and `notes_comments`.
- Validation and preview: validation report before commit; rejects missing or duplicate headers, unsupported columns, CMDB-like columns, unsupported equipment types, duplicate tag/serial within CSV, existing tag/serial in DB, missing canonical tag, partial slot fields, missing slot, non-numeric slot, or occupied slot. No interactive preview page.
- Transaction behavior: validates with a DB read connection, then calls `commit_batch`; commit is all-or-nothing, but validation and commit are separate phases.
- Event and audit behavior: converts rows to `SCAN` ingest rows and appends shared committer events. It does not perform dedicated Issue or Return custody workflows.
- Authentication or role boundary: bypasses Flask roles because it is a CLI; actor is required.
- Actor attribution: free-form `--actor` string stored as ingest operator.
- Direct derived-state writes: yes, through the committer; can create storage assets and slot occupancy when an existing empty slot is specified.
- Tests and maintainer documentation: `tests/test_network_asset_import.py`, `docs/legacy/network_switch_router_staging_template_v1.md`, `docs/legacy/network_switch_router_staging_template_v1.csv`, and admin template page tests.
- Relationship to current workflows: internal legacy utility. Normal operators should use Admin Tools -> Import Assets for bulk Switch/Router import.

### Network Import Admin Template Page

- Name and location: `assettrack/intake/app.py:admin_network_asset_import`, `admin_network_asset_import_template`, `assettrack/intake/templates/admin_network_asset_import.html`.
- Invocation method: admin browser page at `/admin/network-assets/import`; template download at `/admin/network-assets/import/template.csv`.
- Purpose: deprecated guidance and template download for the legacy network CSV import process.
- Input format: none uploaded to the app; template CSV download only.
- Validation and preview: static guidance only; no upload, uploaded-data validation, or preview.
- Transaction behavior: none; no transaction or DB write.
- Event and audit behavior: none.
- Authentication or role boundary: Flask login and admin role required.
- Actor attribution: none.
- Direct derived-state writes: no.
- Tests and maintainer documentation: `tests/test_admin_system_health.py` coverage plus legacy fixture documentation.
- Relationship to current workflows: deprecated operator guidance page. Normal operators should use Admin Tools -> Import Assets.

### Holder CSV Import UI And CLI

- Name and location: `assettrack/holder_import.py`, wrapper `scripts/import_holders_csv.py`, and UI route `assettrack/intake/app.py:admin_holder_import`.
- Invocation method: admin upload page at `/admin/holders/import`, or local CLI `python scripts/import_holders_csv.py <csv> --db <sqlite-path>`.
- Purpose: create or update holders by email and create/reuse organizations needed by holders.
- Input format: CSV with required `organization`, `name`, and `email`.
- Validation and preview: validates header presence, blank/duplicate headers, malformed rows, required values, email format, duplicate email in CSV, and multiple existing holder matches. UI shows preview before confirmation; CLI prints JSON summary. No separate row-by-row confirmation page.
- Transaction behavior: validates before writes, then creates organizations and creates/updates holders in one SQLite transaction.
- Event and audit behavior: admin UI commits write authoritative holder and organization reference tables and exactly one persistent append-only Import History row for a successful import. Holder imports do not append asset custody events. CLI commits do not create Import History rows. This does not inherently bypass event-derived asset custody state.
- Authentication or role boundary: UI requires login and admin role. CLI bypasses Flask roles.
- Actor attribution: admin UI Import History records the authenticated admin actor; CLI imports do not record an actor.
- Direct derived-state writes: directly writes authoritative reference tables, not asset/custody-derived state.
- Tests and operator documentation: `tests/test_holder_import.py`, `tests/test_admin_reference_data.py`, `tests/test_admin_system_health.py`, `docs/BAREBONES_APPLICATION_BOUNDARY.md`, and release user manual holder import steps.
- Relationship to current workflows: UI is supported current CSV workflow with persistent Import History for successful admin UI imports; CLI is an internal unaudited utility. Issue 30-13 owns final preview and audit policy.

### Admin Reference-Data UI

- Name and location: `assettrack/intake/app.py:admin_reference_data` and `assettrack/reference_data.py`.
- Invocation method: admin browser page `/admin/reference-data`.
- Purpose: create organizations, create buildings, rename buildings, activate/deactivate buildings, and create organization-building mappings.
- Input format: action-specific form fields: organization name, building name/id, organization id, building id, active flag.
- Validation and preview: helper validation trims names, rejects blank names, duplicate organization/building names, missing records, inactive building mappings, and duplicate mappings. No import preview; one form submit is the confirmation.
- Transaction behavior: each helper opens a DB connection and commits one action.
- Event and audit behavior: writes authoritative reference tables only; tests confirm building corrections/deactivation do not rewrite asset events or receipt snapshots. No separate administrative audit event exists. This does not inherently bypass event-derived asset custody state.
- Authentication or role boundary: Flask login and admin role required.
- Actor attribution: no actor field is recorded by these helpers.
- Direct derived-state writes: directly writes authoritative reference tables, not asset/custody-derived state.
- Tests and operator documentation: `tests/test_admin_reference_data.py`; admin UI exists under Admin Tools.
- Relationship to current workflows: supported operational seed/reference workflow under Issue 30-14 policy.

### Admin Slot Provisioning UI

- Name and location: `assettrack/intake/app.py:admin_slot_provision`; related helper `assettrack/slots.py:initialize_case_slots` is not called by the route.
- Invocation method: admin browser page `/admin/slots/provision`.
- Purpose: create empty storage capacity for a case.
- Input format: `case_number` and positive integer `slot_count`.
- Validation and preview: uppercases case, validates required fields and integer count, appends slots after current max for the case, and reports DB integrity errors. No preview; form submit is confirmation.
- Transaction behavior: explicit `BEGIN`, `executemany` insert, `commit`, and rollback on integrity or unexpected exception.
- Event and audit behavior: creates empty seed slot records only; no asset event or custody event because no asset moves. No separate administrative audit event exists. This does not inherently bypass event-derived asset custody state.
- Authentication or role boundary: Flask login and admin role required.
- Actor attribution: no actor field recorded for empty slot provisioning.
- Direct derived-state writes: directly writes seed slot tables, not asset/custody-derived state or slot occupancy.
- Tests and operator documentation: `tests/test_admin_slot_provision.py`, `tests/test_basic_auth_guard.py`, and Admin Tools link.
- Relationship to current workflows: supported operational seed workflow under Issue 30-14 policy.

### Slot Helper Functions

- Name and location: `assettrack/slots.py:initialize_case_slots`, plus older direct assignment helpers such as `assign_asset_to_slot`, `move_asset_to_slot`, and `vacate_slot`.
- Invocation method: Python helper calls; no route or CLI found for `initialize_case_slots`.
- Purpose: storage helper functions from earlier/current internal implementation.
- Input format: function arguments.
- Validation and preview: helper-specific validation only; no operator preview.
- Transaction behavior: helper methods use SQLite transactions through `with conn`.
- Event and audit behavior: `initialize_case_slots` creates empty slots without events; older assignment/vacate helpers mutate slot/current home-slot state without appending current movement-proof events.
- Authentication or role boundary: no direct Flask boundary at helper level; callers must enforce it.
- Actor attribution: none at helper level.
- Direct derived-state writes: yes.
- Tests and operator documentation: not documented as operator tools; current admin slot provisioning tests do not call `initialize_case_slots`.
- Relationship to current workflows: internal utility only. Do not expose as an import/seed interface without a separate issue.

### Standard XLSX Inventory Importer

- Name and location: `scripts/import_inventory.py` with wrapper `scripts/import_inventory_docker.sh`.
- Invocation method: documented Docker command `./scripts/import_inventory_docker.sh`, equivalent to `docker compose exec -T assettrack python -m scripts.import_inventory`.
- Purpose: load the approved `.xlsx` inventory workbook into assets, slots, and slot occupancy.
- Input format: workbook at `data/import/BQ26_ETP.xlsx`, sheet `BQ26 main inventory data`, with required columns including `clean_asset_tag`, `case_number`, `slot_helper`, `serial_number`, `equipment_type`, `manufacturer`, `model`, `model_code`, `building_room`, `slot_number`, and `mac_address`.
- Validation and preview: `load_rows()` preflights workbook existence, sheet columns, nonblank asset tag, case number, numeric slot helper, duplicate slot assignment in workbook, and approved equipment type. No UI preview; command prints counts and verification SQL after success.
- Transaction behavior: `run_import()` uses one SQLite transaction; state and events roll back together on integrity or import stop errors.
- Event and audit behavior: directly inserts assets, slots, and occupancy, then appends `ASSET_CREATED` and `SLOT_ASSIGN` events with actor `inventory_import`.
- Authentication or role boundary: bypasses Flask roles because it is a CLI/container command.
- Actor attribution: fixed string `inventory_import`; not linked to an app user.
- Direct derived-state writes: yes, directly writes assets, slots, slot occupancy, and creates a unique slot index if missing.
- Tests and operator documentation: `tests/test_import_inventory.py`, README Fixed-Workbook Inventory Bootstrap, and deployment guide.
- Relationship to current workflows: fixed-workbook/bootstrap path, but constrained by Issue 30-5 for repair, scaling, and deterministic reconciliation. Normal CSV/XLSX asset imports use Admin Tools -> Import Assets. This audit should not decide whether it must move through `commit_batch`.

### Older BQ26 Direct Import Tool

- Name and location: `tools/import_bq26_inventory.py`.
- Invocation method: local Python script, no argparse; hard-coded `data/assettrack.db` and `data/import/BQ26 ETP.xlsx`.
- Purpose: older workbook load for BQ26 inventory.
- Input format: workbook `data/import/BQ26 ETP.xlsx`, sheet `BQ26 main inventory data`, expected columns accessed directly.
- Validation and preview: pandas blank handling, text trim, and equipment type validation only. No explicit required-column report, duplicate preflight, slot collision check, slot occupancy check, or preview.
- Transaction behavior: one SQLite transaction for direct asset and slot inserts; SQLite exceptions roll back.
- Event and audit behavior: does not append asset events; does not write `slot_occupancy`; writes legacy custody value `IN_STOCK`.
- Authentication or role boundary: bypasses Flask roles.
- Actor attribution: none.
- Direct derived-state writes: yes, directly writes assets and slots.
- Tests and operator documentation: no direct tests or supported operator docs found.
- Relationship to current workflows: retire. Any warning, quarantine, removal, or relocation requires a separate approved implementation issue and must not be mixed into this audit.

### BQ26 Root Source Artifacts

- Name and location: root `BQ26 ETP.csv` and `BQ26 ETP.xlsx`.
- Invocation method: none found; historical files in repo root.
- Purpose: apparent older inventory source artifacts.
- Input format: CSV/XLSX with BQ26 inventory columns.
- Validation and preview: none by themselves.
- Transaction behavior: none by themselves.
- Event and audit behavior: none by themselves.
- Authentication or role boundary: none by themselves.
- Actor attribution: none.
- Direct derived-state writes: no.
- Tests and operator documentation: no current supported docs found pointing to root files.
- Relationship to current workflows: legacy artifacts; the current documented XLSX path expects `data/import/BQ26_ETP.xlsx`.

### Legacy SQLite Database Artifact

- Name and location: `legacy/inventory_legacy.db`, documented by `legacy/README.md`.
- Invocation method: none found.
- Purpose: historical reference artifact only.
- Input format: SQLite database with old tables: `inventory`, `issues`, `issue_items`, and `custodian_meta`.
- Validation and preview: none.
- Transaction behavior: none unless manually opened by a user.
- Event and audit behavior: non-current schema; no `asset_events` or current custody/event model.
- Authentication or role boundary: none.
- Actor attribution: none.
- Direct derived-state writes: not by repository code, but manual use would be outside supported persistence.
- Tests and operator documentation: `legacy/README.md` says these files are not used by current AssetTrack and are retained only for reference.
- Relationship to current workflows: legacy inert historical reference artifact, not an operational source. Preserve/delete decisions require Greg approval.

### Fixture Validator Helper

- Name and location: `scripts/validate_fixture.py` and `docs/fixtures/sample_batch.csv`.
- Invocation method: local script `python3 scripts/validate_fixture.py`.
- Purpose: smoke-test the ingest parser and validator against one sample batch CSV.
- Input format: hard-coded `docs/fixtures/sample_batch.csv`.
- Validation and preview: parses and validates only; prints row count, validity, and errors.
- Transaction behavior: none.
- Event and audit behavior: none.
- Authentication or role boundary: bypasses Flask roles but is read/validation-only.
- Actor attribution: none.
- Direct derived-state writes: no.
- Tests and operator documentation: script docstring only; Issue 30-11 confirms it is not wired into `assettrack.ingest commit`.
- Relationship to current workflows: internal utility; not an import path and not an operator-facing preview substitute.

### Network Import Fixtures

- Name and location: `docs/legacy/network_switch_router_staging_template_v1.csv` and `.md`.
- Invocation method: downloaded from admin page or copied from docs.
- Purpose: define the staging contract for switch/router CSV import.
- Input format: CSV template plus markdown contract.
- Validation and preview: documentation only; actual validation occurs in `assettrack/network_asset_import.py`.
- Transaction behavior: none.
- Event and audit behavior: none.
- Authentication or role boundary: docs have none; admin download route requires admin role.
- Actor attribution: none.
- Direct derived-state writes: no.
- Tests and operator documentation: tested through admin template download and used by network import docs.
- Relationship to current workflows: internal/support artifact for the current network CSV process; Issue 30-12 owns canonical interface.

### Import Verification Helper

- Name and location: `tools/verify_import.py`.
- Invocation method: local Python script with hard-coded `data/assettrack.db`.
- Purpose: read row counts and spot checks after import.
- Input format: existing SQLite DB.
- Validation and preview: read-only sanity checks; no pre-commit validation.
- Transaction behavior: none; uses SELECT statements.
- Event and audit behavior: none.
- Authentication or role boundary: bypasses Flask roles but does not write.
- Actor attribution: none.
- Direct derived-state writes: no.
- Tests and operator documentation: no tests or supported docs found.
- Relationship to current workflows: internal utility. It should not be treated as proof that an import path is supported.

### Database Bootstrap And Reset CLI

- Name and location: `assettrack/db.py` command mode, `python -m assettrack.db init|reset`.
- Invocation method: local Python module CLI.
- Purpose: `init` initializes approved schema; `reset` clears operational tables.
- Input format: current `DB_PATH` from `ASSETTRACK_DB_PATH` or default `data/assettrack.db`.
- Validation and preview: `init` asserts schema presence. `reset` checks file existence but has no preview/confirmation in code.
- Transaction behavior: `init` uses schema bootstrap logic. `reset` deletes `slot_occupancy`, `asset_events`, `assets`, and `slots` in one transaction, then runs `VACUUM`.
- Event and audit behavior: `init` can create or backfill default organization state during schema compatibility handling. `reset` deletes append-only event history and operational state.
- Authentication or role boundary: bypasses Flask roles.
- Actor attribution: none.
- Direct derived-state writes: yes. `reset` directly deletes event and state tables.
- Tests and operator documentation: startup/bootstrap behavior is tested in `tests/test_db_init_startup.py` and documented as first-run schema initialization. No supported operator docs found for `reset`.
- Relationship to current workflows: `init` is an internal bootstrap utility. `reset` should be retired or quarantined behind explicit approval because it is incompatible with append-only audit invariants if used on a real operational DB.

## Cross-Cutting Findings

### Paths That Bypass Flask Authentication Or Roles

- Generic `assettrack.ingest` CLI.
- Network Switch/Router CSV CLI.
- Holder CSV import CLI.
- Standard XLSX inventory importer and Docker wrapper.
- Older BQ26 direct importer.
- Fixture validator helper.
- Import verification helper.
- `assettrack.db init|reset`.
- Python helper functions in `assettrack/slots.py` when called outside Flask routes.

### Paths That Bypass Shared Event Behavior

- Holder CSV admin UI import writes authoritative holder/organization reference state and a persistent append-only Import History row for each successful admin UI import; CLI Holder imports remain internal and unaudited. Holder imports do not inherently bypass event-derived asset custody state.
- Admin reference-data UI writes authoritative organizations/buildings/mappings without a separate administrative audit trail; it does not inherently bypass event-derived asset custody state.
- Admin slot provisioning writes empty seed slot records without a separate administrative audit trail; it does not write asset custody state or slot occupancy.
- Standard XLSX inventory importer bypasses `commit_batch`, though it appends `ASSET_CREATED` and `SLOT_ASSIGN` events and tests state/event reconciliation.
- Older BQ26 direct importer bypasses shared committer and appends no events.
- `assettrack.db reset` can delete append-only event history and derived operational state rather than appending history; it must not be used against an operational AssetTrack database.
- Slot helper functions can mutate slot state without current movement-proof event behavior if called directly.

### Paths That Mutate State Directly

- Standard XLSX inventory importer writes assets, slots, slot occupancy, and events directly.
- Older BQ26 direct importer writes assets and slots directly.
- Holder CSV import writes holder and organization reference tables directly; this is reference state, not asset/custody-derived state.
- Admin reference-data UI writes organizations, buildings, and mappings directly; this is reference state, not asset/custody-derived state.
- Admin slot provisioning writes empty seed slot rows directly; this is storage seed state, not asset/custody-derived state or occupancy.
- `assettrack.db reset` deletes operational state and event history directly and is an invariant escalation.
- Slot helper functions can write slots and asset home-slot derived state directly.

### Paths Lacking One Or More Controls

- Generic `assettrack.ingest` CLI: lacks enforced validation, preview, Flask roles, app-user attribution, direct tests, operator docs, and in-file collision checks.
- Network CSV CLI: lacks Flask role enforcement and interactive preview; validation/commit are separate phases.
- Holder import: admin UI Holder CSV imports provide preview/confirmation and create persistent append-only Import History for successful admin UI imports. Holder CLI imports remain internal and unaudited.
- Admin reference-data UI: lacks preview and actor/audit trail.
- Admin slot provisioning UI: lacks preview and actor/audit trail.
- Standard XLSX inventory importer: lacks Flask role enforcement, interactive preview, app-user attribution, and shared-committer behavior; collision reporting relies partly on DB integrity.
- Older BQ26 direct importer: lacks role enforcement, preview, collision checks, slot occupancy, events, tests, and operator docs.
- `assettrack.db reset`: lacks role enforcement, preview/confirmation, actor attribution, and must not be used against an operational AssetTrack database. It can delete append-only event history and derived operational state.

### Duplicate Or Overlapping Import Paths

- Asset import overlap: Generic Add Assets UI, generic `assettrack.ingest`, network CSV CLI, standard XLSX inventory importer, and older BQ26 direct importer can all create asset records or asset-like state.
- Switch/Router overlap: Generic Add Assets can create Switch/Router assets, while network CSV is Switch/Router-specific and Issue 30-12 owns the canonical interface.
- Inventory overlap: Standard XLSX importer and older BQ26 direct importer target similar BQ26-style inventory sources with different filenames and behavior.
- Holder/reference overlap: Holder CSV import can create organizations, while Admin reference-data UI can create organizations directly.
- Slot overlap: Admin slot provisioning creates empty slots; standard XLSX importer creates slots while importing assets; `initialize_case_slots` can seed slots internally.

## Recommended Follow-On Implementation Issues

- Quarantine or retire `tools/import_bq26_inventory.py` after Greg approves the approach. Smallest safe issue: add an explicit warning/block or move to legacy documentation without changing supported import behavior.
- Quarantine or remove root BQ26 source artifacts from operational paths after Greg approves retention/deletion policy.
- Decide whether `assettrack.db reset` should be removed, test-only guarded, or documented as forbidden for operational DBs. This is an invariant escalation requiring a separate approved implementation issue because current code can delete audit history and derived operational state. Issue 30-15 does not remove, guard, or modify it.
- Add a small docs/control issue for `assettrack.ingest` that documents internal-only status and prevents accidental operator exposure, without changing `commit_batch`.
- Add direct CLI tests for `assettrack.ingest` only if Greg wants it retained as more than private plumbing.
- In Issue 30-12, decide whether Switch/Router import remains CLI-backed, becomes an admin upload workflow, or keeps the current admin template page as guidance only.
- Keep Holder import documentation aligned with the current boundary: admin UI CSV imports create persistent append-only Import History for successful imports, while CLI imports remain internal and unaudited.
- In Issue 30-5, repair XLSX inventory import scaling and deterministic reconciliation while preserving first-asset prerequisites and avoiding silent reference-data creation.
- In Issue 30-16, document first-run operator guidance without exposing internal or legacy tools as supported workflows.
- Add a future reference-data audit design only with explicit approval if it requires schema or persistence changes.

## Decisions Requiring Greg Approval

- Any retirement, removal, warning, block, rename, relocation, or quarantine of existing scripts or artifacts.
- Any schema, persistence, or audit mechanism for reference-data actions, import metadata, stronger actor attribution, or validated-import proof.
- Any decision to make CLI import paths operator-facing.
- Any decision to allow imports to auto-create buildings, rooms, holders, organization-building mappings, or slots outside paths already approved by their owning issues.
- Any use or retention policy for `assettrack.db reset`, because it can delete append-only event history and derived operational state and must not be used against an operational database.

## Open Decisions Preserved

- Issue 30-5 still owns inventory import repair, scaling, and deterministic reconciliation.
- Issue 30-12 still decides the canonical Switch and Router import interface.
- Issue 30-13 still owns Holder import preview and audit policy.
- Issue 30-16 still owns operator-facing first-run deployment guidance.
- This audit recommends classifications only; it implements none of them.
