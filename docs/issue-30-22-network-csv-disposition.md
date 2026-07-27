# Issue 30-22 Network CSV Utility Disposition

Classification: planning and workflow decision. Documentation only.

Why it matters: Import Assets is now the canonical bulk asset import workflow. The older Switch/Router CSV utility can still write asset state and append events, so its support status must be explicit without changing runtime behavior in this issue.

## Baseline

Issues 30-12, 30-20, and 30-21 establish the operator workflow:

Admin Tools -> Import Assets -> choose CSV or XLSX -> analyze -> preview -> confirm -> results

Issue 30-15 classifies the Network Switch/Router CSV CLI as an internal legacy utility and the network import admin page as deprecated operator guidance. This document decides the final disposition of the specific utility files, route artifact, fixtures, tests, callers, and docs.

## Decision Summary

| Item | Recommended disposition | Rationale |
| --- | --- | --- |
| `assettrack/network_asset_import.py` | Retain with deprecation warning | It contains the actual legacy parser and writer for Switch/Router-only CSV rows. Tests prove it rejects CMDB-like columns, unsupported equipment types, duplicate tags/serials, missing or occupied slots, and uses `commit_batch` for all-or-nothing writes. It still has maintenance value for exceptional legacy CSV recovery, but it bypasses Flask role enforcement and lacks the canonical upload, preview, confirmation, and results workflow. |
| `scripts/import_network_assets_csv.py` | Retain with deprecation warning | It is only a thin local wrapper around `assettrack.network_asset_import.main`. Retaining it avoids breaking maintainers who intentionally invoke the legacy tool, but it should clearly warn that normal operators must use Import Assets. |
| `/admin/network-assets/import/template.csv` | Replace with a canonical Import Assets artifact | The route is admin-protected and currently serves the legacy Switch/Router-only CSV header. Because the route exists only to distribute the legacy template, its long-term target should be a canonical Import Assets CSV template or redirect/link to one after a scoped implementation issue. Do not remove the route until callers and docs are updated. |
| `docs/fixtures/imports/network/network_switch_router_staging_template_v1.csv` | Move to legacy or quarantine | The file is the legacy Switch/Router-only template served by the deprecated route. It should remain available until the route stops serving it, then move under a legacy/quarantine location so it is not mistaken for the canonical import contract. |
| `docs/fixtures/imports/network/network_switch_router_staging_template_v1.md` | Move to legacy or quarantine | The markdown contract is useful maintainer documentation for the old importer, but it contains CLI invocation guidance. It now says normal operators should use Import Assets. Once the canonical artifact exists, this doc should move with the legacy CSV or be retained only in a legacy technical archive. |

## Evidence

### `assettrack/network_asset_import.py`

- Known callers: `scripts/import_network_assets_csv.py`; `tests/test_network_asset_import.py`.
- Known docs: `docs/issue-30-12-canonical-switch-router-import-workflow.md`, `docs/issue-30-15-legacy-import-tool-audit.md`, and `docs/fixtures/imports/network/network_switch_router_staging_template_v1.md`.
- Behavior: reads CSV, normalizes headers/text, allows only Switch and Router, rejects CMDB-like fields, rejects unsupported columns, validates duplicate asset tags and serial numbers, validates existing empty slots, requires an actor, converts rows to `SCAN` ingest rows, and calls `commit_batch`.
- Boundary: local CLI/module use is outside Flask login, session timeout, and role checks. It has no admin upload page, no interactive preview, no explicit web confirmation, and no web results surface.
- Maintenance value: can still import reviewed legacy Switch/Router staging CSVs through the shared committer if a maintainer explicitly needs that capability.

### `scripts/import_network_assets_csv.py`

- Known callers: direct shell invocation documented by legacy fixture docs and tested in `tests/test_network_asset_import.py`.
- Behavior: imports and runs `assettrack.network_asset_import.main`.
- Boundary: same local CLI boundary as the module; no Flask role enforcement.
- Maintenance value: stable command wrapper for legacy internal use.

### `/admin/network-assets/import/template.csv`

- Known callers: `assettrack/intake/app.py:admin_network_asset_import_template`, `assettrack/intake/templates/admin_network_asset_import.html`, and `tests/test_admin_system_health.py`.
- Behavior: admin-protected download of `docs/fixtures/imports/network/network_switch_router_staging_template_v1.csv`.
- Boundary: route itself is read-only and admin-only, but it distributes a legacy Switch/Router-only artifact tied to a non-canonical CLI process.
- Maintenance value: keeps direct admin access and tests stable until a canonical Import Assets template exists.

### `docs/fixtures/imports/network/network_switch_router_staging_template_v1.csv`

- Known callers: served by `/admin/network-assets/import/template.csv`; referenced by `docs/fixtures/imports/network/network_switch_router_staging_template_v1.md`, Issue 30 docs, roadmap docs, and tests.
- Behavior: header-only legacy CSV template for the Switch/Router-only importer.
- Boundary: docs artifact only; no direct writes.
- Maintenance value: documents the exact legacy field contract while the deprecated route still serves it.

### `docs/fixtures/imports/network/network_switch_router_staging_template_v1.md`

- Known callers: maintainer/operator documentation searches; referenced by Issue 30 audit docs.
- Behavior: documents the legacy CSV fields, duplicate rules, rejected CMDB fields, slot mapping, and old CLI command.
- Boundary: documentation only; currently states normal operators should use Import Assets and the CLI command is legacy internal guidance.
- Maintenance value: explains the old contract well enough to support a controlled migration or rare legacy recovery.

## Related Tests

- `tests/test_network_asset_import.py` covers the legacy parser/writer, duplicate rejection, CMDB-field rejection, slot validation, unsupported equipment type rejection, append-only event expectations, and the wrapper command.
- `tests/test_admin_system_health.py` covers the deprecated network page, its link to Import Assets, and the template download route.

These tests should stay until the relevant runtime behavior or route is intentionally changed in a follow-on issue. If a utility is later moved, warned, or retired, the tests should be updated in that implementation issue.

## Follow-On Issues

1. Add legacy deprecation warnings to `assettrack/network_asset_import.py` and `scripts/import_network_assets_csv.py`.
   - Class: Class 1 if message-only CLI output; Class 2 if exit behavior, arguments, commit behavior, or importer semantics change.
   - Stop if warning behavior would disrupt existing maintenance automation without approval.

2. Add a canonical Import Assets CSV template artifact.
   - Class: Class 1 or documentation-only if it is a static example/template only.
   - Stop if this requires parser, validation, preview, commit, schema, or persistence changes.

3. Change `/admin/network-assets/import/template.csv` to distribute the canonical Import Assets artifact or point directly to the canonical Import Assets workflow.
   - Class: Class 1 if presentation/download target only.
   - Stop if route removal, authorization change, parser behavior, or import behavior changes are required.

4. Move the legacy network CSV template and markdown contract to a legacy/quarantine documentation area after the canonical artifact exists.
   - Class: documentation-only if links and tests are adjusted without runtime behavior changes.
   - Stop if the admin download route still depends on the old path.

5. Retire the legacy Network Switch/Router CSV CLI only after maintainers confirm there are no remaining operational recovery needs.
   - Class: Class 2 because command availability and tests would change.
   - Stop if retirement would require schema, persistence, auth, event, custody, or dependency changes.

## Non-Decisions

- No utility is deleted, relocated, renamed, warned, disabled, or modified in this issue.
- No route, template, script, test, parser, import behavior, schema, event, custody, role, authentication, dependency, or persistence behavior changes in this issue.
- Import Assets remains the canonical operator workflow and is not altered by this decision.
