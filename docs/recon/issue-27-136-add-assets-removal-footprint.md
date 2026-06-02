# Issue 27-136 Recon: Add Assets Removal Footprint

## Conclusion

Preferred path: **hide** the named `Add Assets` entry points in a small Class 1
follow-on issue.

Do not remove or pause routes in the first implementation issue.

Why it matters:

- `GET /add-assets` is a manual batch-creation surface that can be removed from
  normal operator reachability without changing stored facts.
- The shared queue, generic preview, and batch commit code are also used by
  custody-adjacent flows and import tooling. Route or helper deletion would
  widen the blast radius beyond presentation.
- Upload/import does not call the manual `Add Assets` page. It does depend on
  shared creation helpers and batch commit behavior that must remain intact.
- The repo also has separate admin-only manual creation surfaces:
  `GET|POST /admin/assets/new` and `POST /admin/assets/create`. Hiding the named
  `Add Assets` entry is not a full manual-creation pause.

This issue is recon only. No runtime behavior, route, template, test, schema,
persistence, custody workflow, asset record, event, audit-history, or
receipt-truth changes are included.

## Scope Boundary

This recon distinguishes three different concerns:

1. The named `Add Assets` batch workflow:
   `GET /add-assets -> POST / -> POST /add-assets/review -> GET /preview ->
   POST /preview/commit`.
2. Separate admin-only manual creation:
   `GET|POST /admin/assets/new` and `POST /admin/assets/create`.
3. Upload/import creation:
   inventory XLSX import, reviewed network CSV import, and generic ingest CLI.

Only the first concern should be hidden in the smallest follow-on issue.
Pausing every manual creation path is a separate Class 2 decision.

## Sources Reviewed

- `AGENTS.md`
- `README.md`
- `assettrack/intake/app.py`
- `assettrack/intake/to_ingest.py`
- `assettrack/intake/templates/base.html`
- `assettrack/intake/templates/index.html`
- `assettrack/intake/templates/preview.html`
- `assettrack/intake/templates/admin_system.html`
- `assettrack/intake/templates/admin_new_asset.html`
- `assettrack/intake/templates/admin_edit_asset.html`
- `assettrack/intake/templates/403.html`
- `assettrack/intake/templates/404.html`
- `assettrack/assets.py`
- `assettrack/ingest/committer.py`
- `assettrack/ingest/cli.py`
- `assettrack/network_asset_import.py`
- `scripts/import_inventory.py`
- `scripts/import_inventory_docker.sh`
- `tests/test_admin_add_asset_ui.py`
- `tests/test_admin_create_asset.py`
- `tests/test_admin_slot_provision.py`
- `tests/test_basic_auth_guard.py`
- `tests/test_issue_22_2_timeout_ui_lock.py`
- `tests/test_issue_clear_queue.py`
- `tests/test_network_asset_import.py`
- `docs/ingest/opn-2004-format-analysis.md`
- `docs/operator/issue-27-68-workflow-cognition-recon.md`
- `docs/recon/issue-27-73-workflow-surface-compression.md`
- `docs/release/user-manual.md`
- `docs/release/smoke-test.md`
- `docs/release/release-notes.md`
- `docs/roadmap/issue-27-79-stakeholder-feedback-triage.md`
- `docs/roadmap/issue-27-123-import-staged-switches-and-routers.md`

## Current Add Assets Footprint

### Routes and shared workflow code

| Finding | Classification | Why |
| --- | --- | --- |
| `GET /add-assets` renders `index.html`. | safe to hide later | Keep the route initially; remove normal navigation reachability first. |
| `POST /add-assets/review` requires admin role, blocks an empty queue, and redirects to generic `/preview`. | safe to pause later | Pause only in a separate Class 2 issue after direct-link and queue behavior are specified. |
| `POST /` handles queue add, remove, and clear actions for `/add-assets`, `/issue`, and `/return`. | needs separate issue | Keep the shared intake path. It is not import-called directly, but removal would affect custody workflows. |
| `GET /preview`, `POST /preview/discard`, and `POST /preview/commit` support generic staged-asset creation and contain legacy Issue-mode behavior. | needs separate issue | Do not remove generic preview code while it still contains shared and Issue-mode behavior. |
| Multiple fallback redirects in `app.py` return to `add_assets`, including validation, discard, commit, Issue, and Return paths. | needs separate issue | A route removal needs explicit redirect design and custody regression coverage. |
| `build_parsed_rows_from_queue()` and `scan_to_ingest_row()` convert queued scans into validated `SCAN` ingest rows. | safe to pause later | Keep them while `/add-assets` remains live. They are not called by upload/import. |

Why it matters:

Deleting `/add-assets` is not a presentation-only change. The route is a
fallback destination for shared queue behavior, and generic preview still
contains legacy Issue-mode behavior. A hard removal would affect custody
workflow control flow.

### Templates, navigation, buttons, and links

| Finding | Classification | Why |
| --- | --- | --- |
| `base.html` exposes `Add Assets` in the admin menu and marks `/add-assets` active. | safe to hide later | Remove the menu link in the first Class 1 follow-on. |
| `admin_system.html` exposes `Add Assets` as the primary admin-tool link. | safe to hide later | Remove the launcher in the same Class 1 follow-on. |
| `index.html` is the full named batch-entry page with asset type, optional case/slot, scan entry, queue controls, and preview handoff. | safe to pause later | Keep it available but undiscoverable in the first follow-on. A hard pause needs Class 2 approval. |
| `preview.html` presents staged rows and commits generic asset creation when Issue mode is off. | needs separate issue | Its mixed generic-create and legacy Issue-mode behavior should not be edited as part of a link-hide change. |
| `admin_edit_asset.html` links to `admin_new_asset` with `Create Asset`. | needs separate issue | This is a separate admin-only manual creation path, not the named `/add-assets` surface. |
| `admin_new_asset.html` provides the separate `New Asset` form and `Create Asset` submit button. | needs separate issue | Decide separately whether a future full manual-creation pause should hide or pause it. |
| `403.html` and `404.html` use `add_assets` only as an unauthenticated fallback safe page. | safe to remove later | Repoint only when a route-removal issue supplies a replacement destination. |

Why it matters:

The low-cost operator-facing change is limited to two links. The separate admin
create form must not be silently bundled into that change.

### Asset creation helpers and import workflows

| Finding | Classification | Why |
| --- | --- | --- |
| `assettrack/assets.py:create_asset()` inserts an asset row and records a `created` event. | must keep because upload/import depends on it | `assettrack/ingest/committer.py` uses it for new `SCAN` rows. |
| `assettrack/ingest/committer.py:commit_batch()` atomically applies ingest rows. New `SCAN` rows call `create_asset()` and may append `SLOT_ASSIGN`. | must keep because upload/import depends on it | Reviewed network CSV and generic ingest CLI use this path. The manual Add Assets batch workflow also uses it. |
| `assettrack/network_asset_import.py` converts reviewed switch/router CSV rows into `SCAN` ingest rows and calls `commit_batch()`. | must keep because upload/import depends on it | It is independent of `/add-assets` navigation and templates. |
| `assettrack/ingest/cli.py` commits validated JSON rows through `commit_batch()`. | must keep because upload/import depends on it | It is independent of the manual page. |
| `scripts/import_inventory.py` inserts inventory XLSX rows, slots, and occupancy directly. | needs separate issue | It is independent of `/add-assets` and remains a supported path documented in `README.md`, but the script does not append asset events. Audit its event-sourced reconciliation separately. |
| `scripts/import_inventory_docker.sh` runs the inventory import inside the app container. | must keep because upload/import depends on it | It preserves the documented local SQLite import workflow. |
| `_create_admin_asset_in_tx()` backs `GET|POST /admin/assets/new` and `POST /admin/assets/create`. | needs separate issue | It is separate from `/add-assets` and must not be removed while deciding only the named workflow footprint. |

Upload/import dependency finding:

**No upload/import workflow depends on the manual `Add Assets` page or its
navigation links.** Upload/import does depend on shared asset-creation and
ingest code. Keep those helpers unchanged.

Existing import risk outside this issue:

`scripts/import_inventory.py` directly inserts `slots`, `assets`, and
`slot_occupancy` rows. No `asset_events` append is present in that script.
Do not change the script during Add Assets hiding. Open a separate recon issue
to confirm whether this bootstrap-style import is still approved and how its
stored state reconciles with the event log.

### Tests

| Finding | Classification | Why |
| --- | --- | --- |
| `tests/test_admin_add_asset_ui.py` covers `/add-assets`, queue behavior, preview commit, and `/admin/assets/new`. | safe to pause later | Update only the assertions required by an approved follow-on behavior change. Keep coverage for preserved internals. |
| `tests/test_basic_auth_guard.py` covers `/add-assets` return targets, admin-menu visibility, and `/admin/assets/new` authorization. | safe to hide later | The admin-menu visibility assertion will need a focused update when the link is hidden. |
| `tests/test_issue_22_2_timeout_ui_lock.py` covers timeout-lock targets on `/add-assets` and `/preview`. | safe to pause later | Keep while routes remain live. |
| `tests/test_issue_clear_queue.py` covers `/add-assets` queue redirect behavior. | needs separate issue | Keep until a route-removal issue specifies a replacement redirect. |
| `tests/test_admin_create_asset.py` covers `POST /admin/assets/create`. | needs separate issue | Separate admin-create API coverage must remain unless that API is explicitly paused. |
| `tests/test_admin_slot_provision.py` uses `/admin/assets/new` to prepare assets for slot-assignment tests. | needs separate issue | A full manual-creation pause may require new fixture setup; do not mix it into link hiding. |
| `tests/test_network_asset_import.py` covers reviewed CSV import. | must keep because upload/import depends on it | Import regression coverage is independent of the manual page. |

### Documentation and operator wording

| Finding | Classification | Why |
| --- | --- | --- |
| `docs/release/user-manual.md` tells admins to select `Add Assets` and describes how to add assets. | safe to hide later | Update operator guidance in the first follow-on so docs do not advertise a hidden action. |
| `docs/release/smoke-test.md` includes an Add asset scenario using `Add Assets` and `Create Asset`. | needs separate issue | Keep as regression evidence while routes stay live; revise the release smoke plan when product intent for manual creation is explicit. |
| `docs/release/release-notes.md` lists the add asset workflow. | safe to remove later | Historical release wording can remain until a release-doc update is explicitly scoped. |
| `docs/operator/issue-27-68-workflow-cognition-recon.md`, `docs/recon/issue-27-73-workflow-surface-compression.md`, and `docs/roadmap/issue-27-79-stakeholder-feedback-triage.md` describe the current or planned Add Assets surface. | safe to remove later | These are historical recon records. Do not rewrite them during implementation. |
| `docs/ingest/opn-2004-format-analysis.md` documents new-asset creation during batch ingest. | must keep because upload/import depends on it | This is ingest behavior, not manual page guidance. |
| `README.md` and `docs/release/deployment.md` document inventory import commands. | must keep because upload/import depends on it | Import remains supported and independent of `/add-assets`. |

## Preferred Follow-On Implementation

Open one small Class 1 issue:

**Hide the named Add Assets launcher without changing routes or creation
behavior.**

Limit that issue to:

1. Remove the `Add Assets` admin-menu link from
   `assettrack/intake/templates/base.html`.
2. Remove the `Add Assets` launcher from
   `assettrack/intake/templates/admin_system.html`.
3. Update current operator-facing user-manual wording so it no longer directs
   admins to select the hidden launcher.
4. Update only focused navigation assertions required by those template edits.
5. Keep `/add-assets`, `/add-assets/review`, `/preview`, `/preview/commit`,
   shared queue code, import code, helper code, and admin manual-create routes
   unchanged.

Why this is preferred:

- It is strict enough to stop advertising the named workflow.
- It is low-cost and reviewable.
- It does not affect append-only events, custody truth, receipt truth, SQLite
  persistence, offline operation, or upload/import.
- It avoids silently claiming a full hard pause while direct routes and
  separate admin creation surfaces still exist.

## Separate Issue Required for a Hard Pause or Removal

If the product requirement is to block all manual asset creation, open a
separate Class 2 issue before implementation.

That issue must decide:

1. Whether direct requests to `/add-assets` should return `404`, redirect to a
   safe page, or render a deliberate paused-state explanation.
2. Whether `POST /add-assets/review` and generic non-Issue
   `POST /preview/commit` should reject staged manual creation.
3. How shared `POST /`, `/preview`, discard behavior, and fallback redirects
   remain safe for Issue and Return.
4. Whether `GET|POST /admin/assets/new` and `POST /admin/assets/create` are also
   paused.
5. Which release smoke tests replace the current manual-add scenario.
6. Which existing tests remain as regression coverage for upload/import and
   custody flows.

Do not delete `create_asset()`, `commit_batch()`, network CSV import, generic
ingest CLI, or inventory XLSX import as part of that work.

## Stop-Condition Review

- Upload/import depends on manual `Add Assets` behavior: **No.**
- Removing `/add-assets` immediately would affect custody workflow control
  flow: **Yes. Do not remove it in the first follow-on.**
- Schema changes appear necessary: **No.**
- Persistence changes appear necessary: **No.**
- Event payload or history semantic changes appear necessary: **No.**
- Scope beyond recon required for this issue: **No.**

## Verification for This Recon

Run:

```bash
python3 -m compileall assettrack tests scripts
git diff --check
```

No repo-specific docs validation command was found.
