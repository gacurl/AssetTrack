# Network Switch/Router Staging Template v1

## Purpose

Use `network_switch_router_staging_template_v1.csv` only as a legacy network CSV reference for switch and router custody records.

Normal operators should use Admin Tools -> Import Assets for bulk imports. Import Assets supports CSV and XLSX files for Laptop, Switch, and Router records, with analysis, preview, explicit confirmation, atomic commit, and results.

This template feeds the legacy command-line importer for internal or maintainer use. It does not create an admin upload page or add network-management behavior.

AssetTrack tracks equipment custody and storage. It is not a CMDB or network configuration system.

AssetTrack supports these asset categories: Laptop, Switch, and Router. This CSV import path is only for Switch and Router records.

## Allowed Rows

- One physical switch or router per row.
- `equipment_type` must be `switch` or `router`.
- Use custody and storage details only.
- Leave a field blank when the value is unknown.
- Do not add columns without a separate review of the staging contract.

## Fields

| Field | Use |
| --- | --- |
| `asset_tag` | AssetTrack asset tag, when assigned. |
| `barcode` | Scannable custody barcode, when available. |
| `serial_number` | Manufacturer serial number, when available. |
| `equipment_type` | Required. Use `switch` or `router`. |
| `manufacturer` | Equipment manufacturer. |
| `model` | Equipment model. |
| `location_building` | Current storage location or building. |
| `case_identifier` | Storage case identifier, when applicable. |
| `slot_identifier` | Storage slot identifier, when applicable. |
| `notes_comments` | Short custody or storage note. Do not enter configuration data. |

## Required Identifiers

- Every row must include `equipment_type`.
- `asset_tag` is the canonical custody identifier.
- When `asset_tag` is blank, `barcode` may be used as `asset_tag`.
- `serial_number` is useful for reconciliation but is not sufficient by itself.
- Rows without `asset_tag` or `barcode` must be corrected before import.

## Import Mapping

- `case_identifier` maps to an existing `slots.case_name`.
- `slot_identifier` maps to an existing numeric `slots.slot_position` in that case.
- `location_building` maps to `assets.building`.
- Room remains blank because this staging contract does not include a room column.

## Duplicate Handling

- Repeated canonical `asset_tag` values are rejected.
- Repeated `serial_number` values are rejected.
- Existing matching `asset_tag` or `serial_number` values in AssetTrack are rejected.
- The importer does not silently merge, overwrite, or discard duplicate rows.

## Rejected Fields

Do not add or record CMDB-like or network configuration fields, including:

- IP address
- MAC address
- VLAN
- switch port
- topology
- patching
- network relationships
- running configuration
- device configuration

## Import Command

This command is not a normal operator workflow. It is retained as legacy internal guidance for maintainers who explicitly need the old Switch/Router-only CSV importer.

Run from the AssetTrack project after reviewing the CSV:

```bash
python scripts/import_network_assets_csv.py path/to/network_switch_router_staging_template_v1.csv --db data/assettrack.db --actor admin
```

The importer validates headers, supported equipment types, duplicates, CMDB-like columns, and optional slot assignment before committing rows.
