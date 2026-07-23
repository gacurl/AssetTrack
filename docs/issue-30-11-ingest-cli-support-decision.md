# Issue 30-11 Ingest CLI Support Decision

Classification: Class 2 - Logic / Behavior policy. This document is repository investigation and support-status recommendation only. It does not change CLI behavior.

Why it matters: `assettrack.ingest` can write asset state and append events directly to SQLite. Its support boundary must be explicit so operators do not bypass preview, role enforcement, attribution, collision checks, or seed-data policy by accident.

## Current Repository Behavior

| Topic | Evidence | Current behavior |
| --- | --- | --- |
| Entry point | `assettrack/ingest/cli.py:main` | Defines argparse program `assettrack.ingest` with one subcommand: `commit`. Repository evidence shows the invocation shape as module/script code, but no user-facing command documentation was found. |
| Invocation | `assettrack/ingest/cli.py:main` | `commit --db <sqlite-path> --rows-json <json-file>`. The JSON file is loaded with `json.loads(Path(...).read_text())`. |
| Input format | `assettrack/ingest/cli.py:main`; `assettrack/ingest/committer.py:commit_batch` | Expects a JSON list of rows already shaped for the committer. Rows may be `{"row_number": n, "data": {...}}` or flat row dicts because `_apply_rows` supports both. |
| Parser/validator relation | `assettrack/ingest/parser.py:parse_batch`; `assettrack/ingest/validator.py:validate_rows`; `assettrack/ingest/cli.py:main` | Parser and validator exist, but the CLI does not call them. The phrase "validated preview rows" is a caller contract, not enforced by the CLI entry point. |
| Preview behavior | `assettrack/ingest/cli.py:main`; `scripts/validate_fixture.py:main`; `assettrack/intake/app.py:preview`, `preview_validate` | CLI has no preview or validation-report command. Preview exists in UI paths, and `scripts/validate_fixture.py` can parse/validate one sample fixture, but neither is wired into `assettrack.ingest commit`. |
| Commit behavior | `assettrack/ingest/cli.py:main`; `assettrack/ingest/committer.py:commit_batch` | CLI calls `commit_batch(rows, db_path=args.db)`. On `BatchCommitError`, it prints an error and exits 2; otherwise it prints `{"committed_count": n}`. |
| Transaction boundary | `assettrack/ingest/committer.py:commit_batch`, `_apply_rows` | `commit_batch` opens SQLite, bootstraps schema for explicit DB paths, and uses one `with conn` transaction for all rows. Exceptions roll back the batch. |
| Event behavior | `assettrack/ingest/committer.py:_apply_one_event`, `_assign_new_asset_to_home_slot`; `assettrack/assets.py:create_asset`, `update_asset`, `retire_asset` | New `SCAN` can create an asset through `create_asset`, which records a `created` event with actor `system`; committer then records the ingest event with actor from `operator_id`. Slotted new assets also append `SLOT_ASSIGN`. Updates/retirements can append helper events and the ingest event. |
| Actor attribution | `assettrack/ingest/committer.py:_apply_one_event`; `assettrack/assets.py:create_asset` | Actor is a free-form `operator_id` string from row data for the ingest event and slot assignment. It is not linked to a Flask user. The asset helper events use actor `system`. |
| Asset identity | `assettrack/ingest/committer.py:_apply_one_event`, `_asset_exists`; `assettrack/ingest/validator.py:validate_rows` | Committer trims and uppercases `asset_tag`; existing check uses exact stored tag in `_asset_exists`. Validator would enforce `^[A-Z0-9-]+$`, but CLI does not invoke validator. |
| Collision checks | `assettrack/ingest/committer.py:_apply_one_event`, `_assign_new_asset_to_home_slot`; `assettrack/assets.py:create_asset` | Existing asset tags are handled by create-vs-update behavior. New-asset duplicate tag relies on DB uniqueness through `create_asset`. No CLI-level in-file duplicate preflight or serial-number collision check exists. |
| Slot handling | `assettrack/ingest/committer.py:_assign_new_asset_to_home_slot` | New `SCAN` rows may specify `home_slot_id`, or paired `case_number` and `slot_number`. Existing slot must resolve and be empty. Without slot data, the new asset remains unslotted in storage. |
| Custody handling | `assettrack/ingest/committer.py:_apply_one_event`; Issue/Return UI paths in `assettrack/intake/app.py` | The committer accepts `ISSUE`, `RETURN`, `UPDATE`, `RETIRE`, but it applies non-new events through generic `update_asset`/`retire_asset`, not the dedicated Issue/Return workflow that validates holders, receipts, acknowledgments, and queue state. |
| Flask auth and role enforcement | `assettrack/ingest/cli.py:main`; `assettrack/intake/app.py:preview_commit` | CLI does not use Flask login, session timeout, or `@require_role("admin")`. UI commit requires login, admin role, timeout check, validation, and explicit confirmation. |
| Current tests | `tests/test_network_asset_import.py`; `tests/test_admin_add_asset_ui.py`; repository search | No direct test for `assettrack.ingest` CLI was found. `commit_batch` is exercised indirectly by network import and generic Add Assets tests. |
| Relationship to other paths | `assettrack/intake/app.py:preview_commit`; `assettrack/network_asset_import.py:import_network_assets_csv`; `scripts/import_inventory.py:run_import` | UI Add Assets uses parser-shaped queue rows, validates before commit, and requires confirmation. Network CSV validates its own CSV contract then calls `commit_batch`. The XLSX inventory importer is a separate direct importer with its own behavior and tests. Issue 30-5 owns repair, scaling, and deterministic reconciliation for the inventory import workflow. Issue 30-15 determines whether older, unsupported, or legacy import utilities should remain supported, internal, deprecated, or retired. Issue 30-11 does not decide the XLSX importer's final support status. |

## Differences From UI And Import Workflows

- UI Add Assets has entry, queue, preview, confirmation, admin role enforcement, timeout checks, validation, and queue clearing. The CLI has only commit.
- Network CSV import has a domain-specific parser, header contract, rejected CMDB columns, duplicate tag/serial preflight, slot-reference validation, and actor requirement. The CLI has none of those domain checks.
- Holder import validates a specific CSV schema and reports created/updated/errors. The CLI is asset-event oriented and does not handle holders.
- Current XLSX inventory import is a separate direct importer with its own documented path and tests. Its workflow repair, scaling, and deterministic reconciliation belong to Issue 30-5; older or legacy utility support classification belongs to Issue 30-15. It is not evidence that generic JSON commit should be an operator-facing path.

## Risks

- Role enforcement risk: local users can run the CLI against a DB path without Flask authentication or admin role checks.
- Attribution risk: row `operator_id` is free text and not tied to an app user; helper-created asset events can record actor `system`.
- Preview risk: the CLI does not validate or preview rows before commit; it trusts the caller's JSON.
- Collision risk: no in-file duplicate detection, no serial-number collision guard, and no domain-specific import contract.
- Custody risk: `ISSUE` and `RETURN` rows can mutate fields outside the dedicated Issue/Return workflow and without receipt creation or holder/prerequisite checks.
- Hidden administration risk: keeping it operator-facing would create a parallel import path outside Admin Tools and outside the workflow seam.
- Seed-data risk: the CLI can assign slots if row data references existing empty slots, but it has no admin seed-data guidance, controlled UI, or local operating checklist.
- Support risk: no direct CLI tests or operator documentation were found, so operational support would rest on indirect committer behavior.

## Recommended Policy

Recommended classification: internal utility.

The generic `assettrack.ingest` CLI should not be treated as a supported operational interface in its current form. It is useful as a narrow internal commit adapter behind better-controlled workflows, but repository evidence does not show enough validation, preview, role-boundary, attribution, collision, or operator documentation to classify it as operationally supported.

This recommendation does not retire or modify the CLI. Retirement, deprecation warnings, command changes, or documentation exposure require Greg's approval and a separate implementation issue.

## Minimum Controls If Retained As Operational

If Greg chooses to keep `assettrack.ingest` operational, minimum controls should include:

- Documented invocation and support boundary in operator/deployment docs.
- A required validate/preview command or equivalent required preflight before `commit`.
- Hard failure when rows are not explicitly marked as validated by the same toolchain, or another auditable mechanism Greg approves.
- Admin-only local operating procedure because Flask role enforcement does not apply.
- Explicit actor attribution policy, ideally tied to app users or a documented local admin actor format.
- Domain-specific duplicate checks for asset tag and serial-number collisions before commit.
- Clear restriction that generic CLI must not be used for Issue/Return custody workflows unless it implements the same holder, receipt, prerequisite, and commit-gating rules.
- Storage preflight that follows Issue 30-14 seed-data policy: no silent buildings, rooms, mappings, holders, or slots.
- Direct tests for successful commit, validation failure, rollback, actor attribution, duplicate detection, slotted assignment, and forbidden custody use cases.

## Consequences For Milestone 30 Issues

- Issue 30-5 should not rely on `assettrack.ingest` CLI as an operator-facing import path for generic asset imports unless the controls above are implemented in a scoped issue.
- Issue 30-7 may link Admin Tools only to import paths whose support status is defined. It should not expose this generic CLI as an approved import option in its current form.
- Issue 30-12 may continue using `commit_batch` internally for Switch/Router import, but the canonical interface and ownership must be decided there; generic ingest CLI status does not decide network import support.
- Issue 30-15 should include `assettrack.ingest` in the broader import-tool audit as an internal utility with operational-support risks, distinct from direct-state-write legacy tools.
- Issue 30-16 should not include generic `assettrack.ingest` in first-run operator guidance unless Greg approves operational support and the minimum controls exist.

## Future Implementation Work

- Add a focused implementation issue to hide, warn, document, or constrain `assettrack.ingest` after Greg approves the support direction.
- Add direct CLI tests if it remains in the repository as anything more than private/internal plumbing.
- Consider splitting `commit_batch` as the shared internal API from `assettrack.ingest` as a public command, so controlled workflows can keep using the committer without exposing a hidden admin path.
- Revisit whether `ISSUE` and `RETURN` should remain accepted by generic ingest commit once dedicated custody workflows are canonical.
- Decide whether row actor attribution must map to app users or can remain a documented local actor string.

## Decisions Requiring Greg Approval

- Whether to formally mark `assettrack.ingest` as internal utility, deprecated, retired, or supported operational interface.
- Any CLI behavior change, warning, removal, or documentation exposure.
- Any schema, persistence, or audit mechanism needed for validated-import metadata or stronger actor attribution.
- Any decision to allow generic CLI use for custody-changing `ISSUE` or `RETURN` rows.
