# Canonical Asset Import CSV Template

Use `asset_import_template.csv` with Admin Tools -> Import Assets for supported bulk asset imports.

## Workflow

1. Open Admin Tools.
2. Open Import Assets.
3. Choose a CSV or XLSX file.
4. Select Analyze Import.
5. Review the preview.
6. Confirm the preview.
7. Commit the approved rows.
8. Review the results.

Analyze Import creates a preview only. It does not write assets, events, slots, or occupancy. Commit requires explicit confirmation. Approved safe rows commit atomically, and blocked rows do not modify state.

## Required Fields

- `equipment_type` is required.
- `asset_tag` or `barcode` is required.

Supported `equipment_type` values:

- Laptop
- Switch
- Router

## Template Columns

| Column | Use |
| --- | --- |
| `equipment_type` | Required asset type. Use Laptop, Switch, or Router. |
| `asset_tag` | AssetTrack asset tag when assigned. Required when `barcode` is blank. |
| `barcode` | Scannable custody barcode. Required when `asset_tag` is blank. |
| `serial_number` | Manufacturer serial number when available. |
| `manufacturer` | Equipment manufacturer. |
| `model` | Equipment model. |
| `model_code` | Model or catalog code when available. |
| `building_room` | Free-text building or room detail when available. |
| `case_identifier` | Optional storage case identifier. |
| `slot_identifier` | Optional storage slot identifier. |
| `notes_comments` | Short custody or storage note. |

## Storage

Storage fields are optional. Leave `case_identifier` and `slot_identifier` blank when storage is unknown or unavailable.

Rows with missing or unavailable storage may continue as Unslotted only when the admin acknowledges that behavior during preview.

## Unsupported Fields

AssetTrack import is for custody and storage data. Do not add CMDB, IP address, MAC address, VLAN, topology, monitoring, configuration, switch port, patching, network relationship, running configuration, or device configuration fields.
