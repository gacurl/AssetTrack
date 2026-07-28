# Issue 27-93 Recon Network Device Tracking Boundaries

## Conclusion

Close Issue 27-93 as completed by Issues 27-122 and 27-123.

AssetTrack now supports switch/router custody staging and CSV-only import without becoming a CMDB.

```text
AssetTrack tracks custody and storage.
AssetTrack does not track CMDB/network configuration.
```

## Supported Network Device Information

AssetTrack may track a switch or router as a physical custody asset with:

- canonical `asset_tag`, with `barcode` fallback when `asset_tag` is blank
- optional `serial_number`
- `equipment_type`: `switch` or `router`
- manufacturer and model
- building/location
- existing case and numeric slot storage assignment
- short custody/storage notes

This answers the custody questions AssetTrack owns:

- What physical asset is this?
- Where is it stored?
- Which case and slot hold it?
- What identifying details help operators reconcile it?

## Rejected Network Information

AssetTrack must continue to reject CMDB-like and network configuration fields:

- IP address
- MAC address
- VLAN
- switch port
- topology
- patching
- network relationships
- running configuration
- device configuration

These fields do not belong in staging templates, imports, asset notes, or future custody workflows.

## Existing Coverage

Issue 27-122 defined the custody-only staging contract:

- `docs/legacy/network_switch_router_staging_template_v1.csv`
- `docs/legacy/network_switch_router_staging_template_v1.md`
- `docs/roadmap/issue-27-122-stage-switches-and-routers.md`

Issue 27-123 implemented the bounded CSV-only importer:

- `assettrack/network_asset_import.py`
- `scripts/import_network_assets_csv.py`
- `tests/test_network_asset_import.py`
- `docs/roadmap/issue-27-123-import-staged-switches-and-routers.md`

The importer accepts only approved custody fields, rejects CMDB-like columns, validates identifiers and optional existing slot references, and reuses the existing append-only asset ingest path.

## Issue 27-93 Disposition

- classification: completed by later scoped work
- recommended GitHub action: close Issue 27-93 as completed
- completion basis: Issues 27-122 and 27-123 established and enforced the custody-only boundary

## Follow-On Recommendation

No follow-on issue is needed now.

Open a separate, custody-only issue only if operators identify a specific storage or reconciliation gap. Do not open a broad network tracking issue, and do not add CMDB/network configuration fields.

## Non-Goals

- No runtime changes
- No import changes
- No schema or migration changes
- No event, custody, auth, role, or persistence changes
- No XLSX import
- No CMDB/network configuration tracking
