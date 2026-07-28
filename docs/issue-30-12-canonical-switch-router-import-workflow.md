# Issue 30-12 Canonical Switch And Router Import Workflow

Classification: planning and workflow decision. Documentation only.

Why it matters: Switch and Router imports can append asset events and change storage state. Operators need one supported workflow that preserves admin role enforcement, preview-before-commit, explicit confirmation, atomic commit behavior, and offline SQLite operation.

## Decision

The canonical administrator-facing workflow for importing Switches and Routers is:

Admin Tools -> Import Assets -> choose CSV or XLSX -> analyze -> preview -> explicit confirmation -> atomic commit -> results

The canonical route is `/admin/assets/import`. It is the only repository-evidenced administrator-facing Switch/Router import workflow that supports both CSV and XLSX upload, Laptop/Switch/Router equipment types, analysis without database writes, preview results, explicit commit confirmation, reconciliation output, and an admin-only Flask route boundary.

Older Switch/Router utilities remain in the repository in their current state, but they are not the canonical operator workflow for Switch/Router import.

## Evidence

| Evidence | Repository behavior |
| --- | --- |
| Admin Tools action | `assettrack/intake/templates/admin_system.html` lists `Import Assets` in the Assets section, links to `/admin/assets/import`, and labels support as `CSV/XLSX; Laptop, Switch, Router`. |
| Canonical import route | `assettrack/intake/app.py:admin_asset_import` requires login and admin role, accepts `.csv` and `.xlsx`, stores a pending preview, flashes that no database changes were made after analysis, requires `confirm_import=1` for commit, and reports that safe rows were written atomically while blocked rows were left unchanged. |
| Canonical import template | `assettrack/intake/templates/admin_asset_import.html` presents file requirements, required identity, supported equipment types, unslotted acknowledgment, category totals, reconciliation CSV download, and a confirmed commit control. |
| Canonical parser | `assettrack/import_analysis.py` accepts CSV and XLSX rows with supported asset fields, normalizes asset identity and storage fields, rejects missing required structure, and limits equipment type validation through the shared asset type rules. |
| Existing tests | `tests/test_admin_asset_import.py` covers admin page access, CSV and XLSX analysis for Laptop/Switch/Router, preview without writes, commit confirmation, reconciliation output, row classification, blocked rows, and role behavior. |
| Network CSV page | `/admin/network-assets/import` is admin-only, but the template says it has no upload page and points operators to a command-line CSV importer. |
| Network CSV CLI | `assettrack/network_asset_import.py` and `scripts/import_network_assets_csv.py` validate a Switch/Router-only CSV contract and call the shared committer, but they run outside Flask role enforcement and do not provide the canonical admin upload, preview, confirmation, and results workflow. |

## Supported CSV And XLSX Contract For The Canonical Workflow

This decision concerns Switch and Router rows imported through `/admin/assets/import`. The same workflow also supports Laptop rows, but that broader equipment support is outside the Switch/Router decision except where the shared route identifies supported types.

Supported file types:

- `.csv`
- `.xlsx`

Required columns and identity:

- `equipment_type` is required.
- `asset_tag` or `barcode` is required.
- `clean_asset_tag` is accepted by the parser as an identity source but is not exposed as the operator-facing requirement on the admin page.

Supported equipment types:

- Laptop
- Switch
- Router

Supported custody and storage columns:

- `asset_tag`
- `barcode`
- `clean_asset_tag`
- `serial_number`
- `equipment_type`
- `manufacturer`
- `model`
- `model_code`
- `building_room`
- `location_building`
- `case_identifier`
- `slot_identifier`
- `case_number`
- `slot_number`
- `notes_comments`

Storage contract:

- `case_identifier` and `slot_identifier` represent storage assignment intent.
- `case_number` and `slot_number` are alternate storage field names accepted by the canonical parser.
- Slot identifiers are logical integers.
- Missing or unavailable storage can proceed as Unslotted only when the admin acknowledges that behavior during preview.
- Blocked rows do not modify state during commit.

Unsupported network or CMDB fields:

- `ip_address`
- `mac_address`
- `vlan`
- `switch_port`
- `topology`
- `patching`
- `network_relationships`
- `running_configuration`
- `device_configuration`

AssetTrack import remains custody and storage focused. This workflow does not add network discovery, VLAN, IP-address, monitoring, configuration-management, topology, or CMDB behavior.

## Role And Operating Boundaries

| Boundary | Decision |
| --- | --- |
| Admin web workflow | Supported and canonical for Switch/Router operator imports. Flask login and admin role are required by `/admin/assets/import` and its reconciliation CSV route. |
| Operator role | Not authorized for the canonical admin import workflow. Operators should not receive a parallel Switch/Router bulk import path. |
| Local CLI access | Local scripts are outside Flask role checks. A CLI `--actor` string is not equivalent to authenticated admin role enforcement. CLI use is maintenance/internal until a follow-on issue changes that status. |
| Offline operation | Preserved. The canonical workflow continues to use local upload analysis and SQLite persistence; no network service is required. |
| Events and custody | Preserved. This document does not change commit, event, occupancy, reconciliation, or persistence behavior. |

## Entry Point Classifications

| Entry point | Classification | Rationale |
| --- | --- | --- |
| Admin Tools -> Import Assets, `/admin/assets/import` | Supported canonical administrator-facing workflow | Admin-only route; accepts CSV and XLSX; supports Laptop, Switch, and Router; analyzes without writes; provides preview, explicit confirmation, atomic commit, results, and reconciliation output. |
| `/admin/assets/import/reconciliation.csv` | Supported canonical support artifact | Admin-only reconciliation output tied to the current asset import preview/result workflow. |
| Admin Tools -> Import Switch/Router CSV, `/admin/network-assets/import` | Deprecated operator guidance page | It is admin-only and documented, but it provides static guidance and template download only. It points to a local CLI and does not provide upload, preview, confirmation, or results in the web workflow. It remains unchanged in this issue. |
| `docs/legacy/network_switch_router_staging_template_v1.csv` | Legacy network CSV reference artifact | The file documents the older Switch/Router-only CSV contract used by the network CLI. It is not the canonical Import Assets CSV/XLSX workflow. |
| `docs/legacy/network_switch_router_staging_template_v1.md` | Legacy network CSV reference documentation | Documents the older CLI-fed staging contract and CMDB exclusions. It remains useful for classifying the older utility, but it is not the canonical operator workflow. |
| `assettrack/network_asset_import.py` | Internal maintenance utility; deprecated for operator workflow | It validates Switch/Router-only CSV rows and calls `commit_batch`, but it is a CLI path without Flask role enforcement, admin upload, interactive preview, explicit web confirmation, or web results. |
| `scripts/import_network_assets_csv.py` | Internal maintenance wrapper; deprecated for operator workflow | Thin wrapper around `assettrack.network_asset_import.main`; it inherits the CLI boundary and is not canonical. |
| `assettrack.ingest` CLI and `commit_batch` | Internal plumbing for this decision | Issue 30-11 classifies the generic ingest CLI as internal utility. `commit_batch` may remain shared implementation plumbing, but the generic CLI is not a Switch/Router operator workflow. |
| `scripts/import_inventory.py` and `scripts/import_inventory_docker.sh` | Separate supported inventory importer, not canonical Switch/Router operator workflow | Repository evidence shows a separate standard inventory import path for Laptop/Switch/Router and direct SQLite operation. Issue 30-15 owns broader legacy/import-tool support decisions. |
| `/add-assets` manual asset creation workflow | Supported manual workflow, not bulk Switch/Router import | Direct manual entry remains available for individual asset creation, but it is not the canonical bulk Switch/Router import workflow. |

## Follow-On Issues

- Retire, hide, relabel, or replace `Import Switch/Router CSV` in Admin Tools after approval. Presentation-only relabeling can begin as Class 1, but removal or behavior changes need their own scoped issue.
- Update the release user manual section that currently describes `Import Switch/Router CSV` as an operator path so it points administrators to `Import Assets`.
- Decide whether `assettrack/network_asset_import.py` and `scripts/import_network_assets_csv.py` should remain internal maintenance utilities, receive a deprecation warning, or be removed. Any behavior change needs a separate implementation issue.
- Decide whether the legacy network CSV template should remain as a reference artifact, be migrated to the canonical Import Assets contract, or be retired.
- Keep Issue 30-15 as the owner for broader legacy import-tool audit decisions, including direct inventory import paths outside the Switch/Router operator workflow.

## No Runtime Change

This document changes no routes, templates, authorization, parsing, preview behavior, commit behavior, schema, dependencies, authentication, events, occupancy, reconciliation, or persistence. It only records the canonical Switch/Router import workflow decision and classifies existing repository entry points.
