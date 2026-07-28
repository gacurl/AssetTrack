# Issue 27-80 Reconcile Network Equipment Spreadsheet Import Recon

## Conclusion

Close Issue 27-80 as superseded and completed by the safer switch/router-only CSV staging and import path from Issues 27-121, 27-122, 27-123, and 27-93.

The original spreadsheet-import concern is satisfied without adding direct XLSX import or broad raw-spreadsheet ingestion.

```text
AssetTrack tracks custody and storage.
AssetTrack does not track CMDB/network configuration.
```

## Current Safe Path

Reviewed switch/router custody rows use the canonical CSV staging contract:

- `docs/legacy/network_switch_router_staging_template_v1.csv`
- `docs/legacy/network_switch_router_staging_template_v1.md`
- `docs/roadmap/issue-27-122-stage-switches-and-routers.md`

The bounded importer is:

- `assettrack/network_asset_import.py`
- `scripts/import_network_assets_csv.py`
- `tests/test_network_asset_import.py`
- `docs/roadmap/issue-27-123-import-staged-switches-and-routers.md`

The network-device boundary recon is:

- `docs/roadmap/issue-27-93-recon-network-device-tracking-boundaries.md`

## Relationship To Issue 27-121

No dedicated Issue 27-121 roadmap document is tracked in the repo.

The applicable artifact policy is recorded in:

- `docs/ingest/import-artifact-standards.md`

That standard keeps canonical CSV and Markdown templates reviewable in git while keeping XLSX files and ad-hoc spreadsheets local-only.

## Spreadsheet Boundary

Direct XLSX import remains intentionally out of scope.

Bulk or raw spreadsheet ingestion also remains intentionally blocked. Operators must review and reduce source data into the approved switch/router-only CSV contract before import.

This matters because raw spreadsheets may contain unsupported columns, inconsistent identifiers, or CMDB-like data that AssetTrack must not store.

## Supported Custody Information

The approved CSV path supports:

- canonical `asset_tag`, with `barcode` fallback when `asset_tag` is blank
- optional serial number
- `switch` or `router` equipment type
- manufacturer and model
- building/location
- existing case and numeric slot storage assignment
- short custody/storage notes

## Rejected Network Information

AssetTrack must continue to reject:

- IP address
- MAC address
- VLAN
- switch port
- topology
- patching
- network relationships
- running configuration
- device configuration

## Issue 27-80 Disposition

- classification: superseded and completed by later scoped work
- recommended GitHub action: close Issue 27-80 as completed
- completion basis: the reviewed CSV-only path replaces the risky broad spreadsheet-import concept

## Follow-On Recommendation

No follow-on issue is needed now.

Open a separate, custody-only issue only if operators identify a specific staging, storage, or reconciliation gap. Do not add direct XLSX import, bulk raw-spreadsheet ingestion, or CMDB/network configuration tracking.

## Non-Goals

- No runtime changes
- No import behavior changes
- No XLSX import
- No `.gitignore` changes
- No schema or migration changes
- No event, custody, auth, role, or persistence changes
- No CMDB/network configuration tracking
